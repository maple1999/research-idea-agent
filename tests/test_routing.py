import json

import httpx

from app.engine import Engine
from app.provider import CompatibleProvider, Settings
from app.routing import ModelConfiguration, ModelRouter
from app.store import Store
from tests.test_research import EmptyLiterature, result, setup_run


async def test_task_routing_uses_correct_endpoints_keys_and_review(tmp_path):
    store = Store(tmp_path / "test.db")
    project, run = setup_run(store, max_calls=4, max_tokens=150000)
    store.update_run(run["id"], budget=run["budget"] | {"use_search": True})
    seen = []
    profiles = {role: Settings(f"https://{role}.test/v1", f"{role}-test-key", role)
                for role in ("exploration", "literature", "review")}
    def respond(request):
        body = json.loads(request.content)
        role = body["model"]
        assert request.url.host == f"{role}.test"
        assert request.headers["Authorization"] == f"Bearer {role}-test-key"
        assert not ({"max_tokens", "max_completion_tokens", "response_format"} & body.keys())
        seen.append(role)
        step = result()
        if len(seen) == 1:
            step = step.model_copy(update={"next_action": "search", "search_query": "video evidence compression"})
        elif role == "literature":
            step = step.model_copy(update={"next_action": "develop"})
        elif role == "review":
            step.directions[0].innovation = "Revised after constructive review."
        return httpx.Response(200, json={"choices": [{"message": {"content": step.model_dump_json()},
                                                     "finish_reason": "stop"}], "usage": {"total_tokens": 500}})
    router = ModelRouter(ModelConfiguration(profiles, {role: role for role in profiles}), httpx.MockTransport(respond))
    await Engine(store, router, EmptyLiterature(store)).execute(run["id"])
    assert seen == ["exploration", "literature", "exploration", "review"]
    assert store.run(run["id"])["tokens"] == 2000
    assert store.run(run["id"])["status"] == "completed"
    assert store.project(project["id"])["directions"][0]["innovation"] == "Revised after constructive review."
    events = store.events(project["id"])
    assert [e["payload"]["task"] for e in events if e["kind"] == "research.developing"] == seen


async def test_single_model_has_no_forced_extra_review_and_accepts_large_output(tmp_path):
    store = Store(tmp_path / "test.db")
    project, run = setup_run(store, max_tokens=150000)
    def respond(request):
        step = result()
        step.directions[0].innovation = "Detailed mechanism. " * 2000
        return httpx.Response(200, json={"choices": [{"message": {"content": step.model_dump_json()}}],
                                         "usage": {"total_tokens": 12000}})
    settings = Settings("https://example.test/v1", "test-key", "model")
    router = ModelRouter(ModelConfiguration.single(settings), httpx.MockTransport(respond))
    await Engine(store, router, EmptyLiterature(store)).execute(run["id"])
    assert store.run(run["id"])["calls"] == 1
    assert store.run(run["id"])["tokens"] == 12000
    assert len(store.project(project["id"])["directions"][0]["innovation"]) > 8000


async def test_failed_reviewer_preserves_proposal_and_never_falls_back(tmp_path):
    store = Store(tmp_path / "test.db")
    project, run = setup_run(store, max_tokens=150000)
    profiles = {role: Settings(f"https://{role}.test/v1", "test-key", role) for role in ("primary", "critic")}
    seen = []
    def respond(request):
        name = json.loads(request.content)["model"]
        seen.append(name)
        if name == "critic":
            return httpx.Response(500)
        return httpx.Response(200, json={"choices": [{"message": {"content": result().model_dump_json()}}]})
    router = ModelRouter(ModelConfiguration(profiles, {"exploration": "primary", "literature": "primary", "review": "critic"}), httpx.MockTransport(respond))
    await Engine(store, router, EmptyLiterature(store)).execute(run["id"])
    assert seen == ["primary", "critic"]
    assert store.run(run["id"])["status"] == "failed"
    assert store.project(project["id"])["directions"]


def test_role_prompts_give_each_model_distinct_work():
    provider = CompatibleProvider(Settings("https://example.test/v1", "test-key", "model"))
    project = {"question": "Question", "constraints": "", "sources": [], "directions": [], "feedback": [], "memories": []}
    prompts = [provider.request(project | {"current_task": role})["messages"][1]["content"]
               for role in ("exploration", "literature", "review")]
    assert len(set(prompts)) == 3


async def test_shared_literature_and_review_model_still_performs_review_task(tmp_path):
    store = Store(tmp_path / "test.db")
    _, run = setup_run(store, max_calls=3, max_tokens=150000)
    store.update_run(run["id"], next_action="literature")
    settings = Settings("https://example.test/v1", "test-key", "same-model")
    configuration = ModelConfiguration({"primary": settings, "analyst": settings},
                                      {"exploration": "primary", "literature": "analyst", "review": "analyst"})
    seen = []
    def respond(request):
        body = json.loads(request.content)
        seen.append(json.loads(body["messages"][2]["content"])["current_task"])
        return httpx.Response(200, json={"choices": [{"message": {"content": result().model_dump_json()}}]})
    await Engine(store, ModelRouter(configuration, httpx.MockTransport(respond)), EmptyLiterature(store)).execute(run["id"])
    assert seen == ["literature", "review"]
