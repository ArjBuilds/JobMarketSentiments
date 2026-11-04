"""Stream the real-time aggregates over a WebSocket.

Run with:  uvicorn backend.api:app --port 8000

    GET /health                                       {"ok": true, "store": "sqlite"}
    WS  /ws/aggregates?dataset=live|synthetic         a snapshot on connect, then one
                                                      message each time it changes

A message is backend.store.snapshot_dict plus "type" ("snapshot" or
"update") and "sent_at". dataset=synthetic is SYNTHETIC data and says so
("synthetic": true); it needs BACKEND_STORE=clickhouse.

One poller per dataset, not per client: every POLL_SECONDS it reads the
aggregate tables once and sends the result to every connected client, only
if it changed. A hundred open dashboards cost the database one small query
every POLL_SECONDS, and an unchanged feed sends nothing.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from backend import config
from backend.store import open_store

POLL_SECONDS = 2.0
DATASETS = ("live", "synthetic")

log = logging.getLogger("backend.api")


class Hub:
    """The clients of one dataset and the latest snapshot sent to them."""

    def __init__(self, dataset: str):
        self.dataset = dataset
        self.clients: set[WebSocket] = set()
        self.latest: dict | None = None

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.clients.discard(ws)


def stamp(snapshot: dict, kind: str) -> dict:
    return {"type": kind, "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **snapshot}


async def poll(hub: Hub, store) -> None:
    """Read the dataset's aggregates every POLL_SECONDS; send them on when they change."""
    while True:
        try:
            # The store's client blocks, so it runs off the event loop.
            snapshot = await asyncio.to_thread(store.aggregates, hub.dataset == "synthetic")
        except Exception:  # the stream must outlive a database restart; log and poll again
            log.exception("reading %s aggregates failed", hub.dataset)
        else:
            if snapshot != hub.latest:
                hub.latest = snapshot
                await hub.broadcast(stamp(snapshot, "update"))
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    datasets = DATASETS if config.STORE == "clickhouse" else ("live",)
    app.state.hubs = {d: Hub(d) for d in datasets}
    # One store per poller: a clickhouse-connect client is one session, and
    # ClickHouse refuses a second query on a session that is still running one.
    stores = [open_store(config.STORE, config.SQLITE_PATH) for _ in app.state.hubs]
    tasks = [asyncio.create_task(poll(hub, store)) for hub, store in zip(app.state.hubs.values(), stores)]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for store in stores:
        store.close()


app = FastAPI(title="Job postings live aggregates", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "store": config.STORE, "datasets": list(app.state.hubs)}


@app.websocket("/ws/aggregates")
async def aggregates(ws: WebSocket, dataset: str = "live") -> None:
    hub = app.state.hubs.get(dataset)
    if hub is None:
        await ws.close(code=1008, reason=f"dataset must be one of {list(app.state.hubs)}")
        return
    await ws.accept()
    hub.clients.add(ws)
    try:
        if hub.latest is not None:
            await ws.send_json(stamp(hub.latest, "snapshot"))
        while True:  # nothing is expected from the client; this notices it leaving
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
