import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.engine import Engine
from app.main import create_app
from app.provider import Settings
from app.store import Store
from tests.test_research import EmptyLiterature, FakeProvider, result, setup_run


def values(**updates):
    return {"models": [{"id": "default", "api_base": "https://example.test/v1",
                        "api_key": None, "model": "updated-model"} | updates]}


def test_update_is_immediate_keeps_key_and_survives_restart(tmp_path, monkeypatch):
    app = create_app(tmp_path, FakeProvider(), EmptyLiterature)
    with TestClient(app) as client:
        old = app.state.engine.provider
        response = client.post('/api/config', json=values())
        assert response.status_code == 200
        assert response.json()["model"] == "updated-model"
        assert response.json()["models"][0]["has_api_key"]
        assert "api_key" not in response.json()["models"][0]
        assert app.state.engine.provider.settings.api_key == "test"
        assert old.settings.model == "fixture"
        assert not hasattr(app.state.engine.provider.settings, "max_output")
    monkeypatch.setattr(Settings, "load", lambda: FakeProvider.settings)
    restarted = create_app(tmp_path, literature_factory=EmptyLiterature)
    assert restarted.state.engine.provider.settings.model == "updated-model"
    assert restarted.state.engine.provider.settings.api_key == "test"


def test_endpoint_change_requires_its_key_and_secrets_are_not_returned(tmp_path):
    app = create_app(tmp_path, FakeProvider(), EmptyLiterature)
    with TestClient(app) as client:
        assert client.post('/api/config', json=values(api_base="https://other.test/v1")).status_code == 422
        assert app.state.engine.provider.settings.api_base == "https://example.test/v1"
        changed = client.post('/api/config', json=values(api_base="https://other.test/v1", api_key="new-test-key"))
        assert changed.status_code == 200 and "new-test-key" not in changed.text
        assert "new-test-key" not in client.get('/api/config').text
        bad = client.post('/api/config', json=values(api_key="private-test-key", model=""))
        assert bad.status_code == 422 and "private-test-key" not in bad.text
        hostile = client.post('/api/config', json=values(), headers={"Origin": "https://evil.test"})
        assert hostile.status_code == 403


def test_failed_persistence_does_not_change_running_configuration(tmp_path, monkeypatch):
    from app.configuration import Configuration
    def fail(*args):
        raise OSError("test")
    monkeypatch.setattr(Configuration, "save", fail)
    app = create_app(tmp_path, FakeProvider(), EmptyLiterature)
    with TestClient(app) as client:
        assert client.post('/api/config', json=values()).status_code == 500
        assert app.state.engine.provider.settings.model == "fixture"


@pytest.mark.asyncio
async def test_inflight_call_finishes_and_next_call_uses_new_provider(tmp_path):
    store = Store(tmp_path / "test.db")
    _, run = setup_run(store)
    old = FakeProvider(result().model_copy(update={"next_action": "develop"}), block=True)
    new = FakeProvider()
    engine = Engine(store, old, EmptyLiterature(store))
    task = asyncio.create_task(engine.execute(run["id"]))
    await old.entered.wait()
    engine.provider = new
    old.release.set()
    await task
    assert old.count == 1 and new.count == 1
    assert store.run(run["id"])["tokens"] == 700
    assert store.run(run["id"])["status"] == "completed"


def test_legacy_config_preserves_credentials_but_drops_old_limits(tmp_path):
    from app.configuration import Configuration
    legacy = {"api_base": "https://legacy.test/v1", "api_key": "legacy-test-key", "model": "legacy-model",
              "max_output": 8000, "output_mode": "json_schema", "token_parameter": "max_tokens"}
    (tmp_path / 'provider-settings.json').write_text(json.dumps(legacy), encoding="utf-8")
    loaded = Configuration(tmp_path).load(FakeProvider.settings)
    assert loaded.models["default"].api_key == "legacy-test-key"
    assert not hasattr(loaded.models["default"], "max_output")
    assert all(v == "default" for v in loaded.assignments.values())


def test_legacy_environment_output_cap_is_ignored(monkeypatch):
    monkeypatch.setenv("IDEA_MAX_OUTPUT_TOKENS", "8000")
    settings = Settings.load()
    assert not hasattr(settings, "max_output")


def test_multiple_models_routes_key_preservation_and_deletion(tmp_path, monkeypatch):
    body = values()
    body["models"].append({"id": "critic", "api_base": "https://review.test/v1", "api_key": "critic-test-key", "model": "review-model"})
    body["assignments"] = {"exploration": "default", "literature": "default", "review": "critic"}
    app = create_app(tmp_path, FakeProvider(), EmptyLiterature)
    with TestClient(app) as client:
        assert client.post('/api/config', json=body).status_code == 200
        body["models"][1]["api_key"] = None
        assert client.post('/api/config', json=body).status_code == 200
        router = app.state.engine.provider
        assert router.for_task("review").settings.api_key == "critic-test-key"
        assert router.for_task("exploration").settings.api_key == "test"
        assert "critic-test-key" not in client.get('/api/config').text
        orphan = {"models": body["models"][:1], "assignments": body["assignments"]}
        assert client.post('/api/config', json=orphan).status_code == 422
        assert len(app.state.engine.provider.configuration.models) == 2
        duplicate = {"models": [body["models"][0], body["models"][0]]}
        assert client.post('/api/config', json=duplicate).status_code == 422
    monkeypatch.setattr(Settings, "load", lambda: FakeProvider.settings)
    restored = create_app(tmp_path, literature_factory=EmptyLiterature)
    assert restored.state.engine.provider.for_task("review").settings.model == "review-model"
    with TestClient(restored) as client:
        assert client.post('/api/config', json=values()).status_code == 200
        assert len(client.get('/api/config').json()["models"]) == 1
