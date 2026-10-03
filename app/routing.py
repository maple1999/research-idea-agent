"""Immutable per-save model routing, captured once at each research step."""
from dataclasses import dataclass

from .provider import CompatibleProvider, Settings

TASKS = ("exploration", "literature", "review")
TASK_NAMES = {"exploration": "研究探索", "literature": "文献分析", "review": "方案审查"}


@dataclass(frozen=True)
class ModelConfiguration:
    models: dict[str, Settings]
    assignments: dict[str, str]

    @classmethod
    def single(cls, settings):
        return cls({"default": settings}, dict.fromkeys(TASKS, "default"))

    def public(self):
        default = next(iter(self.models.values()))
        return {"configured": all(self.models[mid].ready for mid in self.assignments.values()),
                "model": default.model, "experiments_enabled": False,
                "models": [{"id": mid, "api_base": s.api_base, "model": s.model,
                            "has_api_key": bool(s.api_key)} for mid, s in self.models.items()],
                "assignments": self.assignments}


class ModelRouter:
    def __init__(self, configuration, transport=None):
        self.configuration = configuration
        self.transport = transport
        self.providers = {mid: CompatibleProvider(s, transport) for mid, s in configuration.models.items()}

    @property
    def settings(self):
        return self.for_task("exploration").settings

    def for_task(self, task):
        return self.providers[self.configuration.assignments[task]]

    def separate_reviewer(self):
        return self.configuration.assignments["review"] != self.configuration.assignments["exploration"]
