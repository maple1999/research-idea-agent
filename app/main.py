import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import Engine
from .literature import Literature
from .models import (CommandInput, FeedbackInput, MemoryInput, ProjectInput, RunInput,
                     SelectionInput, SourceInput)
from .provider import CompatibleProvider, Settings
from .store import Conflict, Store, uid


def create_app(data_dir=None, provider=None, literature_factory=Literature):
    settings = Settings.load()
    store = Store(Path(data_dir or os.getenv("IDEA_DATA_DIR", "data")) / "research.db")
    engine = Engine(store, provider or CompatibleProvider(settings), literature_factory(store))

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        await engine.close()

    app = FastAPI(title="Research Idea Agent", lifespan=lifespan)
    app.state.store, app.state.engine = store, engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_origin(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in {
                "http://localhost:8765", "http://127.0.0.1:8765",
                "http://localhost:5173", "http://127.0.0.1:5173",
            }:
                return JSONResponse({"detail": "不接受来自其他网站的修改请求。"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def project_or_404(project_id):
        project = store.project(project_id)
        if project is None:
            raise HTTPException(404, "课题不存在")
        return project

    def pause_for_edit(project_id):
        for run in store.runs(project_id):
            if run["status"] == "running":
                store.update_run(run["id"], status="pausing", reason="研究内容已更新，正在结束旧步骤。")

    @app.get("/api/config")
    def config():
        actual = engine.provider.settings
        return {"configured": actual.ready, "model": actual.model,
                "output_mode": actual.output_mode, "experiments_enabled": False}

    @app.get("/api/projects")
    def projects():
        return [{k: p[k] for k in ("id", "title", "question", "revision", "created")} for p in store.projects()]

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput):
        return store.create_project(body.model_dump())

    @app.get("/api/projects/{project_id}")
    def project(project_id: str):
        return project_or_404(project_id) | {"runs": store.runs(project_id)}

    @app.post("/api/projects/{project_id}/sources")
    def source(project_id: str, body: SourceInput):
        p = project_or_404(project_id)
        if len(p["sources"]) >= 100:
            raise HTTPException(422, "当前版本每个课题最多导入 100 份材料。")
        item = body.model_dump(mode="json") | {"id": "src_" + uid(), "kind": "user_passage"}
        updated = store.mutate(project_id, p["revision"], lambda p: p["sources"].append(item),
                               "source.added", "已导入研究材料：" + body.title)
        pause_for_edit(project_id)
        return updated

    @app.post("/api/projects/{project_id}/feedback")
    def feedback(project_id: str, body: FeedbackInput):
        p = project_or_404(project_id)
        if body.direction_id and body.direction_id not in {d["id"] for d in p["directions"]}:
            raise HTTPException(404, "方向不存在")
        def edit(p):
            p["feedback"].append(body.model_dump() | {"id": uid()})
            for d in p["directions"]:
                if body.direction_id is None or body.direction_id == d["id"]:
                    d["needs_update"] = True
        updated = store.mutate(project_id, body.expected_revision, edit, "feedback.applied",
                               "已记录反馈，相关判断将在继续探索时更新。")
        pause_for_edit(project_id)
        return updated

    @app.post("/api/projects/{project_id}/directions/{direction_id}/selection")
    def selection(project_id: str, direction_id: str, body: SelectionInput):
        p = project_or_404(project_id)
        if direction_id not in {d["id"] for d in p["directions"]}:
            raise HTTPException(404, "方向不存在")
        return store.mutate(project_id, body.expected_revision,
                            lambda p: p["selections"].update({direction_id: body.selection}),
                            "direction.selected", "方向选择已更新")

    @app.post("/api/projects/{project_id}/memories")
    def memory(project_id: str, body: MemoryInput):
        p = project_or_404(project_id)
        if set(body.source_ids) - {s["id"] for s in p["sources"]}:
            raise HTTPException(422, "经验包含未知来源")
        item = body.model_dump() | {"id": uid(), "status": "user_note", "scope": "project"}
        updated = store.mutate(project_id, p["revision"], lambda p: p["memories"].append(item),
                               "memory.added", "已保存带适用条件的课题经验")
        pause_for_edit(project_id)
        return updated

    @app.post("/api/projects/{project_id}/runs", status_code=201)
    async def start(project_id: str, body: RunInput):
        project_or_404(project_id)
        if not engine.provider.settings.ready:
            raise HTTPException(422, "请先配置本地模型服务，重启后开始探索。")
        run = store.create_run(project_id, body.model_dump())
        engine.start(run["id"])
        return run

    @app.post("/api/runs/{run_id}/commands")
    async def command(run_id: str, body: CommandInput):
        run = store.run(run_id)
        if run is None:
            raise HTTPException(404, "探索不存在")
        if body.command == "pause":
            if run["status"] == "running":
                store.update_run(run_id, status="pausing")
                store.event(run["project_id"], "run.pausing",
                            {"summary": "正在暂停；当前请求完成后停止新调用。"})
        elif body.command == "cancel":
            if run["status"] not in ("completed", "cancelled"):
                engine.stop(run_id, "cancelled", "本轮探索已结束，已有研究记录保留。")
        elif run["status"] == "paused":
            if not engine.provider.settings.ready:
                raise HTTPException(422, "模型服务尚未配置")
            store.update_run(run_id, status="running", reason="")
            store.event(run["project_id"], "run.resumed", {"summary": "继续发展当前研究方案"})
            engine.start(run_id)
        else:
            raise HTTPException(409, "当前状态无法恢复，请新建一轮探索。")
        return store.run(run_id)

    @app.get("/api/projects/{project_id}/events")
    async def events(project_id: str, request: Request, after: int = 0):
        project_or_404(project_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(422, "事件游标无效") from None
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                for event in store.events(project_id, cursor):
                    cursor = event["seq"]
                    yield f"id: {cursor}\nevent: update\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/projects/{project_id}/history")
    def history(project_id: str):
        project_or_404(project_id)
        return store.history(project_id)

    @app.get("/api/projects/{project_id}/export")
    def export(project_id: str):
        return JSONResponse(project_or_404(project_id), headers={
            "Content-Disposition": 'attachment; filename="research-snapshot.json"'})

    dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app


app = create_app()
