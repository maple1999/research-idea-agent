import asyncio
import time

from .provider import ProviderError
from .store import Conflict


class Engine:
    def __init__(self, store, provider, literature):
        self.store, self.provider, self.literature = store, provider, literature
        self.tasks = {}

    def start(self, run_id):
        previous = self.tasks.get(run_id)
        if previous and not previous.done():
            return
        task = asyncio.create_task(self.execute(run_id))
        self.tasks[run_id] = task

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self, run_id, status, reason):
        if self.store.run(run_id)["status"] == "cancelled":
            return
        run = self.store.update_run(run_id, status=status, reason=reason)
        self.store.event(run["project_id"], "run." + status, {"summary": reason, "run_id": run_id})

    def check(self, run_id):
        run = self.store.run(run_id)
        if run["status"] == "pausing":
            self.stop(run_id, "paused", "已暂停，可修改方向后恢复。")
            return False
        return run["status"] == "running"

    async def execute(self, run_id):
        while self.check(run_id):
            run = self.store.run(run_id)
            project = self.store.project(run["project_id"])
            budget = run["budget"]
            remaining = budget["max_minutes"] * 60 - run["elapsed"]
            if remaining <= 0 or run["calls"] >= budget["max_calls"]:
                self.stop(run_id, "completed", "本轮预算已用完，当前研究成果已保存。")
                return
            if budget["use_search"] and run["next_action"] == "search":
                query = run["search_query"] or project["question"][:200]
                self.store.event(project["id"], "research.searching", {"summary": "查找相关基础：" + query})
                started = time.monotonic()
                search_applied = False
                try:
                    sources, origin = await self.literature.search(query, timeout=min(30, remaining))
                    def add_sources(p):
                        existing = {s["id"] for s in p["sources"]}
                        p["sources"].extend(s for s in sources if s["id"] not in existing)
                    if self.store.run(run_id)["status"] == "running":
                        project = self.store.mutate(project["id"], project["revision"], add_sources,
                                                    "sources.updated", f"检索得到 {len(sources)} 篇摘要（{origin}）")
                        search_applied = True
                except Conflict:
                    self.stop(run_id, "paused", "用户已更新研究内容，旧检索结果未覆盖当前版本。")
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    search_applied = True
                    self.store.event(project["id"], "source.unavailable",
                                     {"summary": "文献来源暂不可用，将依据已导入材料继续；检索失败已记录。"})
                finally:
                    self.store.update_run(run_id, elapsed=run["elapsed"] + time.monotonic() - started,
                                          searched=search_applied,
                                          next_action="develop" if search_applied else "search")
                if not self.check(run_id):
                    return
                run = self.store.run(run_id)
                project = self.store.project(project["id"])
                remaining = budget["max_minutes"] * 60 - run["elapsed"]
                if remaining <= 0:
                    self.stop(run_id, "completed", "本轮时间预算已用完，检索记录已保存。")
                    return
            project = project | {"search_enabled": budget["use_search"]}
            try:
                reserved = self.provider.reserve(project)
            except ProviderError as exc:
                self.stop(run_id, "failed", str(exc))
                return
            if run["tokens"] + reserved > budget["max_tokens"]:
                self.stop(run_id, "completed", "剩余 token 预算不足以预留下一次调用，当前结果已保存。")
                return
            self.store.update_run(run_id, calls=run["calls"] + 1, tokens=run["tokens"] + reserved,
                                  usage_estimated=True)
            self.store.event(project["id"], "research.developing",
                             {"summary": "分析重要问题、具体机制与已有基础，发展候选研究方案。"})
            started = time.monotonic()
            try:
                result, usage = await self.provider.generate(project, timeout=min(180, remaining))
                current = self.store.run(run_id)
                self.store.update_run(run_id, tokens=run["tokens"] + (reserved if usage is None else usage),
                                      usage_estimated=run["usage_estimated"] or usage is None)
                if current["status"] == "cancelled":
                    return
                valid_sources = {s["id"] for s in project["sources"][-10:]}
                if len({d.id for d in result.directions}) != len(result.directions):
                    raise ProviderError("模型返回重复方向标识，当前版本保持不变。")
                for direction in result.directions:
                    cited = {sid for c in direction.claims for sid in c.source_ids}
                    cited.update(c.source_id for c in direction.comparisons)
                    if cited - valid_sources:
                        raise ProviderError("输出引用了未提供的来源，当前版本保持不变。")
                    if any(c.status == "supported" and not c.source_ids for c in direction.claims):
                        raise ProviderError("有依据的主张缺少来源，当前版本保持不变。")

                def apply_result(p):
                    incoming = [d.model_dump() | {"assessed_revision": project["revision"]} for d in result.directions]
                    ids = {d["id"] for d in incoming}
                    preserved = [d for d in p["directions"] if d["id"] not in ids
                                 and p["selections"].get(d["id"]) == "retained"]
                    p["directions"] = incoming + preserved
                self.store.mutate(project["id"], project["revision"], apply_result,
                                  "directions.updated", result.summary)
                self.store.update_run(run_id, step=run["step"] + 1,
                                      next_action=result.next_action, search_query=result.search_query[:300])
                self.store.event(project["id"], "research.next", {"summary": result.rationale})
                if result.next_action == "finish":
                    if self.check(run_id):
                        self.stop(run_id, "completed", "本轮研究方案已形成，可审查、纠正或继续发展。")
                    return
            except Conflict:
                self.stop(run_id, "paused", "研究内容已被修正，旧模型输出未覆盖当前判断；可恢复并使用新版本。")
                return
            except ProviderError as exc:
                self.stop(run_id, "failed", str(exc))
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stop(run_id, "failed", "研究步骤执行失败，已有结果已保留。")
                return
            finally:
                latest = self.store.run(run_id)
                self.store.update_run(run_id, elapsed=latest["elapsed"] + time.monotonic() - started)
            await asyncio.sleep(0)
