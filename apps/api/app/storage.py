from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings
from .schemas import Alert, ScreenerSettings, WatchlistEntry, Workspace


def _now():
    return datetime.now(timezone.utc)


def _ensure_path(path: str) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    return file_path


def _default_workspaces() -> list[Workspace]:
    return [
        Workspace(id="top-gainers", title="Топ роста", market="BINANCE_SPOT", sortingType="top_gainers", sortingTypeRange="24h"),
        Workspace(id="trades", title="Сделки", market="BINANCE_FUTURES", sortingType="trades", sortingTypeRange="1h"),
        Workspace(id="densities", title="Плотности", market="BYBIT_FUTURES", sortingType="volume", sortingTypeRange="1h"),
        Workspace(id="levels", title="Уровни", market="OKX_SPOT", sortingType="formations_first", sortingTypeRange="1h"),
        Workspace(id="watchlist", title="Watchlist", market="BINANCE_SPOT", sortingType="watchlist_first", sortingTypeRange="24h"),
    ]


@dataclass
class AppState:
    workspaces: list[Workspace] = field(default_factory=_default_workspaces)
    current_settings: ScreenerSettings = field(default_factory=ScreenerSettings)
    watchlist: list[WatchlistEntry] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    ai_cache: dict[str, dict] = field(default_factory=dict)


class JsonStateStore:
    def __init__(self, file_path: str | None = None) -> None:
        self.file_path = _ensure_path(file_path or settings.state_file)
        self.state = self._load()

    def _load(self) -> AppState:
        if not self.file_path.exists():
            state = AppState()
            self._save(state)
            return state
        payload = json.loads(self.file_path.read_text(encoding="utf-8"))
        workspaces = [Workspace.model_validate(item) for item in payload.get("workspaces", [])] or _default_workspaces()
        settings_payload = payload.get("current_settings") or {}
        current_settings = ScreenerSettings.model_validate(settings_payload)
        watchlist = [WatchlistEntry.model_validate(item) for item in payload.get("watchlist", [])]
        alerts = [Alert.model_validate(item) for item in payload.get("alerts", [])]
        ai_cache = payload.get("ai_cache", {})
        return AppState(
            workspaces=workspaces,
            current_settings=current_settings,
            watchlist=watchlist,
            alerts=alerts,
            ai_cache=ai_cache,
        )

    def _serialize(self, state: AppState) -> dict:
        return {
            "workspaces": [workspace.model_dump(mode="json") for workspace in state.workspaces],
            "current_settings": state.current_settings.model_dump(mode="json"),
            "watchlist": [entry.model_dump(mode="json") for entry in state.watchlist],
            "alerts": [alert.model_dump(mode="json") for alert in state.alerts],
            "ai_cache": state.ai_cache,
        }

    def _save(self, state: AppState) -> None:
        self.file_path.write_text(json.dumps(self._serialize(state), ensure_ascii=False, indent=2), encoding="utf-8")

    def persist(self) -> None:
        self._save(self.state)

    def get_workspaces(self) -> list[Workspace]:
        return self.state.workspaces

    def upsert_workspace(self, workspace: Workspace) -> Workspace:
        for index, existing in enumerate(self.state.workspaces):
            if existing.id == workspace.id:
                self.state.workspaces[index] = workspace
                self.persist()
                return workspace
        self.state.workspaces.append(workspace)
        self.persist()
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        before = len(self.state.workspaces)
        self.state.workspaces = [workspace for workspace in self.state.workspaces if workspace.id != workspace_id]
        changed = len(self.state.workspaces) != before
        if changed:
            self.persist()
        return changed

    def get_settings(self) -> ScreenerSettings:
        return self.state.current_settings

    def update_settings(self, settings_payload: ScreenerSettings) -> ScreenerSettings:
        self.state.current_settings = settings_payload
        self.persist()
        return settings_payload

    def get_watchlist(self) -> list[WatchlistEntry]:
        return self.state.watchlist

    def set_watchlist(self, items: list[WatchlistEntry]) -> list[WatchlistEntry]:
        self.state.watchlist = items
        self.persist()
        return items

    def get_alerts(self) -> list[Alert]:
        return self.state.alerts

    def upsert_alert(self, alert: Alert) -> Alert:
        for index, existing in enumerate(self.state.alerts):
            if existing.id == alert.id:
                self.state.alerts[index] = alert
                self.persist()
                return alert
        self.state.alerts.append(alert)
        self.persist()
        return alert

    def delete_alert(self, alert_id: str) -> bool:
        before = len(self.state.alerts)
        self.state.alerts = [alert for alert in self.state.alerts if alert.id != alert_id]
        changed = len(self.state.alerts) != before
        if changed:
            self.persist()
        return changed

    def get_ai_cache(self, cache_key: str) -> dict | None:
        item = self.state.ai_cache.get(cache_key)
        if not item:
            return None
        expires_at = datetime.fromisoformat(item["expiresAt"])
        if expires_at < _now():
            self.state.ai_cache.pop(cache_key, None)
            self.persist()
            return None
        return item["value"]

    def set_ai_cache(self, cache_key: str, value: dict, ttl_minutes: int) -> None:
        self.state.ai_cache[cache_key] = {
            "value": value,
            "expiresAt": (_now() + timedelta(minutes=ttl_minutes)).isoformat(),
        }
        self.persist()


store = JsonStateStore()
