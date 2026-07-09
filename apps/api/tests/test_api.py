from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import AiFormationInput, Candle, FormationSignal, FormationType, ScreenerRow


def _ai_payload():
    formation = FormationSignal(
        type=FormationType.ActiveCoins,
        symbol="ETH/USDT",
        market="BINANCE_SPOT",
        timeframe="5m",
        direction="neutral",
        score=78,
        distancePct=0.2,
        price=100.0,
        reason="Активность выше порога",
        detectedAt=datetime.now(timezone.utc),
    )
    candles = [
        Candle(ts=datetime.now(timezone.utc), open=99, high=101, low=98, close=100, volume=1000, trades=120),
        Candle(ts=datetime.now(timezone.utc), open=100, high=102, low=99, close=101, volume=1200, trades=130),
    ]
    metrics = ScreenerRow(
        symbol="ETH/USDT",
        market="BINANCE_SPOT",
        exchange="BINANCE",
        price=101,
        priceChange1m=1,
        priceChange3m=2,
        priceChange5m=3,
        priceChange15m=4,
        priceChange30m=5,
        priceChange1h=6,
        priceChange2h=7,
        priceChange6h=8,
        priceChange12h=9,
        priceChange24h=10,
        volumeSum1m=1,
        volumeSum5m=2,
        volumeSum1h=3,
        volumeSum24h=4,
        tradesSum1m=1,
        tradesSum5m=2,
        tradesSum1h=3,
        tradesSum24h=4,
        natr5_14=1.5,
        volatility=0.2,
        btcCorrelation=0.1,
        hasAlert=False,
        inWatchlist=False,
        active=True,
        formation=formation,
    )
    return AiFormationInput(
        symbol="ETH/USDT",
        market="BINANCE_SPOT",
        timeframe="5m",
        currentPrice=101,
        formation=formation,
        candles=candles,
        horizontalLevels=[],
        trendLevels=[],
        densities=[],
        metrics=metrics,
    )


def test_markets_and_workspace_roundtrip(test_client):
    response = test_client.get("/api/markets")
    assert response.status_code == 200
    assert response.json()["markets"]

    workspaces = test_client.get("/api/workspaces").json()["workspaces"]
    workspace = workspaces[0]
    workspace["title"] = "Updated title"
    save = test_client.put(f"/api/workspaces/{workspace['id']}", json=workspace)
    assert save.status_code == 200

    reloaded = test_client.get("/api/workspaces").json()["workspaces"]
    assert any(item["title"] == "Updated title" for item in reloaded)


def test_alert_and_ai_json(test_client):
    payload = _ai_payload()
    ai_response = test_client.post("/api/formations/fake-id/ai-analysis?mode=quick", json=payload.model_dump(mode="json"))
    assert ai_response.status_code == 200
    body = ai_response.json()
    assert body["summary"]
    assert isinstance(body["whyDetected"], list)
    assert "confidenceAdjustment" in body

    alert = {
        "id": "alert-1",
        "userId": "local-user",
        "active": True,
        "type": "formationDetected",
        "symbols": ["ETH/USDT"],
        "market": "BINANCE_SPOT",
        "direction": "all",
        "interval": "5m",
        "threshold": 0,
        "distance": 0,
        "lifetime": 0,
        "corrosionTime": 0,
        "watchlistOnly": False,
        "sound": "default",
        "telegramNotification": False
    }
    created = test_client.post("/api/alerts", json=alert)
    assert created.status_code == 200
    assert test_client.get("/api/alerts").json()["items"]


def test_websocket_receives_rescan_event(test_client):
    with test_client.websocket_connect("/ws") as ws:
        response = test_client.post("/api/formations/rescan")
        assert response.status_code == 200
        for _ in range(5):
            message = ws.receive_json()
            if message["topic"] == "formation.detected":
                assert message["payload"]["count"] >= 0
                break
        else:
            raise AssertionError("formation.detected event not received")
