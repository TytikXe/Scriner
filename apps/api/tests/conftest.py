from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.ai as ai_mod
import app.main as main_mod
import app.services as services_mod
import app.storage as storage_mod


@pytest.fixture()
def test_client(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    store = storage_mod.JsonStateStore(str(state_file))
    monkeypatch.setattr(storage_mod, "store", store)
    monkeypatch.setattr(services_mod, "store", store)
    monkeypatch.setattr(services_mod.service, "store", store)
    monkeypatch.setattr(ai_mod, "store", store)
    monkeypatch.setattr(main_mod.service, "store", store)
    with TestClient(main_mod.app) as client:
        yield client
