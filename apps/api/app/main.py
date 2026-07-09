from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .ai import analyze_formation, analyze_formations_batch
from .config import settings
from .schemas import (
    Alert,
    AlertsResponse,
    AiFormationInput,
    CandleResponse,
    DensitiesResponse,
    EventMessage,
    FormationListResponse,
    MarketsResponse,
    ScreenerDataResponse,
    ScreenerSettings,
    WatchlistEntry,
    WatchlistResponse,
    Workspace,
    WorkspaceListResponse,
)
from .services import service


app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Broadcaster:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.clients.discard(websocket)

    async def send(self, topic: str, payload: dict[str, Any]) -> None:
        message = EventMessage(topic=topic, payload=payload).model_dump(mode="json")
        stale: set[WebSocket] = set()
        for client in list(self.clients):
            try:
                await client.send_json(message)
            except Exception:
                stale.add(client)
        for client in stale:
            self.disconnect(client)


broadcaster = Broadcaster()


@app.get("/api/markets", response_model=MarketsResponse)
async def get_markets():
    return await service.get_markets()


@app.get("/api/screener/data", response_model=ScreenerDataResponse)
async def get_screener_data():
    return await service.get_screener_data()


@app.get("/api/screener/settings", response_model=ScreenerSettings)
async def get_screener_settings():
    return service.get_settings()


@app.put("/api/screener/settings", response_model=ScreenerSettings)
async def put_screener_settings(settings_payload: ScreenerSettings):
    return service.update_settings(settings_payload)


@app.get("/api/workspaces", response_model=WorkspaceListResponse)
async def get_workspaces():
    return WorkspaceListResponse(workspaces=service.get_workspaces())


@app.post("/api/workspaces", response_model=Workspace)
async def post_workspace(workspace: Workspace):
    return service.update_workspace(workspace)


@app.put("/api/workspaces/{workspace_id}", response_model=Workspace)
async def put_workspace(workspace_id: str, workspace: Workspace):
    if workspace.id != workspace_id:
        raise HTTPException(status_code=400, detail="workspace id mismatch")
    return service.update_workspace(workspace)


@app.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    if not service.delete_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"ok": True}


@app.get("/api/chart/candles", response_model=CandleResponse)
async def get_chart_candles(symbol: str, market: str, timeframe: str = "5m", limit: int = 300):
    candles = await service.get_candles(symbol, market, timeframe, limit)
    return CandleResponse(symbol=symbol, market=market, exchange=market.split("_")[0], timeframe=timeframe, candles=candles)


@app.get("/api/orderbook/densities", response_model=DensitiesResponse)
async def get_orderbook_densities(symbol: str, market: str):
    return await service.get_densities(symbol, market)


@app.get("/api/formations", response_model=FormationListResponse)
async def get_formations():
    return await service.get_formations()


@app.post("/api/formations/rescan", response_model=FormationListResponse)
async def post_formations_rescan():
    result = await service.rescan_formations()
    await broadcaster.send("formation.detected", {"count": len(result.formations)})
    return result


@app.post("/api/formations/{formation_id}/ai-analysis")
async def post_formation_ai_analysis(formation_id: str, payload: AiFormationInput, mode: str = "quick"):
    result = await analyze_formation(payload, mode=mode)
    return result.model_dump(mode="json")


@app.post("/api/formations/batch-ai-analysis")
async def post_formations_batch_ai_analysis(payload: list[AiFormationInput], mode: str = "quick"):
    result = await analyze_formations_batch(payload, mode=mode)
    return [item.model_dump(mode="json") for item in result]


@app.get("/api/watchlist", response_model=WatchlistResponse)
async def get_watchlist():
    return WatchlistResponse(items=service.get_watchlist())


@app.put("/api/watchlist", response_model=WatchlistResponse)
async def put_watchlist(items: list[WatchlistEntry]):
    return WatchlistResponse(items=service.update_watchlist(items))


@app.get("/api/alerts", response_model=AlertsResponse)
async def get_alerts():
    return AlertsResponse(items=service.get_alerts())


@app.post("/api/alerts", response_model=Alert)
async def post_alert(alert: Alert):
    return service.upsert_alert(alert)


@app.put("/api/alerts/{alert_id}", response_model=Alert)
async def put_alert(alert_id: str, alert: Alert):
    if alert.id != alert_id:
        raise HTTPException(status_code=400, detail="alert id mismatch")
    return service.upsert_alert(alert)


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    if not service.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="alert not found")
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)


async def _event_loop():
    while True:
        try:
            data = await service.get_screener_data()
            matches = service.evaluate_alerts(data.rows)
            await broadcaster.send("screener.update", data.model_dump(mode="json"))
            await broadcaster.send("coin.metrics", {"rows": len(data.rows)})
            await broadcaster.send("density.update", {"generatedAt": data.generatedAt.isoformat()})
            await broadcaster.send("alert.triggered", {"count": len(matches), "matches": matches[:10]})
        except Exception:
            pass
        await asyncio.sleep(1)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_event_loop())
