import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.engine import Engine
from app.literature import Literature
from app.main import create_app
from app.models import ResearchStep
from app.provider import CompatibleProvider, ProviderError, Settings
from app.store import Conflict, Store


def result(source_ids=None):
    return ResearchStep.model_validate({
        "summary": "已形成一个用于接口测试的研究构思", "next_action": "finish",
        "search_query": "", "rationale": "等待研究者检查机制。", "directions": [{
            "id": "direction_a", "title": "任务条件下的信息保留", "question": "如何保留未来问题所需的信息？",
            "innovation": "比较固定与问题条件下的信息选择。", "impact": "关注短暂事件的证据保留。",
            "feasibility": "先分析现有表征与选择规则。", "mechanism": {"object": "视频表征",
                "locus": "编码器与语言模型之间", "operation": "条件化选择", "output": "压缩后的表示序列",
                "signal": "问题相关性", "assumptions": ["问题可在选择前获得"]},
            "claims": [{"text": "研究问题条件下的选择规则", "status": "proposed", "source_ids": source_ids or []}],
            "comparisons": [], "unknowns": ["未知问题下如何选择"], "next_step": "比较信息可用时点。"}]})


class FakeProvider:
    settings = Settings("https://example.test/v1", "test", "fixture", "json_object", "max_tokens", 1000)

    def __init__(self, step=None, block=False):
        self.step = step or result()
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.block = block
        self.count = 0

    def reserve(self, p):
        return 2000

    async def generate(self, p, timeout=120):
        self.count += 1
        self.entered.set()
        if self.block:
            await self.release.wait()
        return self.step, 350


class EmptyLiterature:
    def __init__(self, store):
        pass

    async def search(self, query, timeout=30):
        return [], "fixture"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "research.db")


def setup_run(store, max_calls=2, max_tokens=10000):
    p = store.create_project({"title": "Test", "question": "A meaningful research question", "constraints": ""})
    r = store.create_run(p["id"], {"max_calls": max_calls, "max_tokens": max_tokens,
                                  "max_minutes": 5, "use_search": False})
    return p, r


async def test_complete_without_experiment(store):
    p, r = setup_run(store)
    provider = FakeProvider()
    await Engine(store, provider, EmptyLiterature(store)).execute(r["id"])
    assert store.run(r["id"])["status"] == "completed"
    assert store.run(r["id"])["tokens"] == 350
    assert not store.run(r["id"])["usage_estimated"]
    assert store.project(p["id"])["directions"][0]["id"] == "direction_a"
    assert store.history(p["id"])[-1]["directions"] == []


async def test_edit_during_call_never_overwrites_correction(store):
    p, r = setup_run(store)
    provider = FakeProvider(block=True)
    engine = Engine(store, provider, EmptyLiterature(store))
    task = asyncio.create_task(engine.execute(r["id"]))
    await provider.entered.wait()
    store.mutate(p["id"], 1, lambda p: p.update(question="Corrected research question"), "edit", "corrected")
    provider.release.set()
    await task
    assert store.project(p["id"])["question"] == "Corrected research question"
    assert store.project(p["id"])["directions"] == []
    assert store.run(r["id"])["status"] == "paused"
    assert store.run(r["id"])["tokens"] == 350


async def test_pause_preserves_checkpoint_then_resume(store):
    p, r = setup_run(store)
    step = result().model_copy(update={"next_action": "develop"})
    provider = FakeProvider(step, block=True)
    engine = Engine(store, provider, EmptyLiterature(store))
    task = asyncio.create_task(engine.execute(r["id"]))
    await provider.entered.wait()
    store.update_run(r["id"], status="pausing")
    provider.release.set()
    await task
    assert store.run(r["id"])["status"] == "paused"
    assert store.run(r["id"])["step"] == 1
    assert len(store.project(p["id"])["directions"]) == 1
    store.update_run(r["id"], status="running")
    await engine.execute(r["id"])
    assert provider.count == 2
    assert store.run(r["id"])["status"] == "completed"


async def test_cancel_discards_inflight_result_but_accounts_usage(store):
    p, r = setup_run(store)
    provider = FakeProvider(block=True)
    engine = Engine(store, provider, EmptyLiterature(store))
    task = asyncio.create_task(engine.execute(r["id"]))
    await provider.entered.wait()
    engine.stop(r["id"], "cancelled", "cancelled")
    provider.release.set()
    await task
    assert store.run(r["id"])["status"] == "cancelled"
    assert store.run(r["id"])["tokens"] == 350
    assert store.project(p["id"])["directions"] == []


async def test_unknown_citation_never_commits(store):
    p, r = setup_run(store)
    await Engine(store, FakeProvider(result(["fabricated"])), EmptyLiterature(store)).execute(r["id"])
    assert store.run(r["id"])["status"] == "failed"
    assert store.project(p["id"])["directions"] == []


async def test_budget_checked_before_model_call(store):
    _, r = setup_run(store, max_tokens=1000)
    provider = FakeProvider()
    await Engine(store, provider, EmptyLiterature(store)).execute(r["id"])
    assert provider.count == 0
    assert store.run(r["id"])["status"] == "completed"


async def test_pause_during_search_retrieves_pending_sources_on_resume(store):
    p, r = setup_run(store)
    store.update_run(r["id"], budget=r["budget"] | {"use_search": True}, next_action="search",
                     search_query="video token compression")
    entered, release = asyncio.Event(), asyncio.Event()
    class BlockingLiterature:
        async def search(self, query, timeout=30):
            entered.set()
            await release.wait()
            return [{"id": "src_pending", "title": "Paper", "text": "Abstract"}], "fixture"
    provider = FakeProvider()
    engine = Engine(store, provider, BlockingLiterature())
    task = asyncio.create_task(engine.execute(r["id"]))
    await entered.wait()
    store.update_run(r["id"], status="pausing")
    release.set()
    await task
    assert not store.run(r["id"])["searched"]
    assert provider.count == 0
    store.update_run(r["id"], status="running")
    await engine.execute(r["id"])
    assert store.project(p["id"])["sources"][0]["id"] == "src_pending"


async def test_provider_failure_after_cancel_keeps_cancelled_status(store):
    _, r = setup_run(store)
    class FailingProvider(FakeProvider):
        async def generate(self, p, timeout=120):
            self.entered.set()
            await self.release.wait()
            raise ProviderError("Network failure")
    provider = FailingProvider()
    engine = Engine(store, provider, EmptyLiterature(store))
    task = asyncio.create_task(engine.execute(r["id"]))
    await provider.entered.wait()
    engine.stop(r["id"], "cancelled", "cancelled")
    provider.release.set()
    await task
    assert store.run(r["id"])["status"] == "cancelled"


async def test_model_plans_targeted_search_before_retrieval(store):
    p, r = setup_run(store)
    store.update_run(r["id"], budget=r["budget"] | {"use_search": True})
    seen = []
    class Planner(FakeProvider):
        async def generate(self, project, timeout=120):
            assert project["search_enabled"]
            seen.append("model")
            return result().model_copy(update={"next_action": "search",
                                               "search_query": "task conditioned video tokens"}), 350
    class Search:
        async def search(self, query, timeout=30):
            seen.append(query)
            return [], "fixture"
    await Engine(store, Planner(), Search()).execute(r["id"])
    assert seen == ["model", "task conditioned video tokens", "model"]


def test_missing_key_cannot_start_a_production_run(tmp_path):
    provider = CompatibleProvider(Settings("https://example.test/v1", "", "model", "text", "max_tokens", 1000))
    with TestClient(create_app(tmp_path, provider, EmptyLiterature)) as client:
        p = client.post('/api/projects', json={"title": "Project", "question": "Research question"}).json()
        assert client.post(f'/api/projects/{p["id"]}/runs', json={}).status_code == 422
        assert client.get(f'/api/projects/{p["id"]}').json()["runs"] == []


def test_recovery_and_revision_conflict(store):
    p, r = setup_run(store)
    store.update_run(r["id"], calls=1, tokens=2000, usage_estimated=True)
    store.recover()
    assert store.run(r["id"])["status"] == "paused"
    assert store.run(r["id"])["tokens"] == 2000
    with pytest.raises(Conflict):
        store.create_run(p["id"], r["budget"])
    with pytest.raises(Conflict):
        store.mutate(p["id"], 99, lambda p: p.update(question="wrong"), "edit", "wrong")
    assert store.project(p["id"])["revision"] == 1


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "text"])
async def test_provider_modes_and_usage(mode):
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": result().model_dump_json()}}], "usage": {"total_tokens": 523}})
    settings = Settings("https://example.test/v1", "secret-test", "model", mode, "max_completion_tokens", 1000)
    provider = CompatibleProvider(settings, httpx.MockTransport(handle))
    project = {"question": "question", "constraints": "", "sources": [], "directions": [], "feedback": [], "memories": []}
    step, usage = await provider.generate(project)
    assert usage == 523 and step.directions[0].id == "direction_a"
    assert seen[0]["max_completion_tokens"] == 1000
    assert ("response_format" in seen[0]) == (mode != "text")


async def test_provider_error_is_sanitized():
    def handle(request):
        return httpx.Response(401, text="leaked-private-provider-key")
    provider = CompatibleProvider(FakeProvider.settings, httpx.MockTransport(handle))
    project = {"question": "question", "constraints": "", "sources": [], "directions": [], "feedback": [], "memories": []}
    with pytest.raises(ProviderError) as exc:
        await provider.generate(project)
    assert "401" in str(exc.value)
    assert "leaked" not in str(exc.value)


async def test_arxiv_normalizes_and_caches(store):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>http://arxiv.org/abs/1234.56789v1</id><title>A paper</title>
          <summary>A relevant abstract</summary><published>2025-01-01</published>
          </entry></feed>''')
    literature = Literature(store, httpx.MockTransport(handle))
    first, origin = await literature.search("video tokens")
    second, origin2 = await literature.search("video tokens")
    assert first == second and len(calls) == 1 and origin2 == "cache"
    assert first[0]["url"].startswith("https://arxiv.org/abs/")
    assert first[0]["kind"] == "abstract"


def test_api_import_feedback_export_and_origin(tmp_path):
    app = create_app(tmp_path, FakeProvider(), EmptyLiterature)
    with TestClient(app) as client:
        p = client.post('/api/projects', json={"title": "Project", "question": "Research question"}).json()
        pid = p["id"]
        r = client.post(f'/api/projects/{pid}/sources', json={"title": "Paper", "text": "An actual supplied method passage.", "url": "https://example.org/paper"})
        assert r.status_code == 200 and r.json()["revision"] == 2
        assert client.post(f'/api/projects/{pid}/feedback', json={"expected_revision": 1, "kind": "correction", "text": "correct"}).status_code == 409
        r = client.post(f'/api/projects/{pid}/feedback', json={"expected_revision": 2, "kind": "correction", "text": "correct"})
        assert r.status_code == 200 and r.json()["revision"] == 3
        assert client.get(f'/api/projects/{pid}/export').json()["feedback"][0]["text"] == "correct"
        assert len(client.get(f'/api/projects/{pid}/history').json()) == 3
        bad = client.post('/api/projects', json={"title": "Bad", "question": "Malicious cross-origin"}, headers={"Origin": "https://evil.test"})
        assert bad.status_code == 403
        assert "secret" not in client.get('/api/config').text
        assert client.get('/api/projects/missing').status_code == 404


def test_no_private_material_in_publish_tree():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "research").exists()
    assert not (root / "ResearchStudio").exists()
    assert not (root / "OpenAI4S").exists()
