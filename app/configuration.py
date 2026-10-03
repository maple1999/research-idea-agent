"""Local provider overrides; never included in project exports or event payloads."""
import json
import os
import tempfile
from dataclasses import asdict

from .models import ModelsInput
from .provider import Settings
from .routing import ModelConfiguration


class Configuration:
    def __init__(self, directory):
        self.path = directory / "provider-settings.json"

    def load(self, default):
        previous = ModelConfiguration.single(default)
        if not self.path.exists():
            return previous
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if "models" not in raw:
                # Import older single-model saves; deliberately discard their old caps.
                raw = {"models": [{k: raw[k] for k in ("api_base", "api_key", "model")}]}
            return self.resolve(ModelsInput.model_validate(raw), previous)
        except (ValueError, KeyError, OSError):
            raise RuntimeError("本地模型配置无法读取，请检查 data/provider-settings.json。") from None

    def resolve(self, values, previous):
        models = {}
        for item in values.models:
            if item.id in models:
                raise ValueError("模型标识不能重复。")
            endpoint = str(item.api_base).rstrip("/")
            key = item.api_key.get_secret_value().strip() if item.api_key else ""
            old = previous.models.get(item.id)
            if not key:
                if old is None or endpoint != old.api_base.rstrip("/"):
                    raise ValueError("新增模型或更换 API 地址时，请填写对应密钥。")
                key = old.api_key
            if not key:
                raise ValueError("请填写 API 密钥。")
            models[item.id] = Settings(endpoint, key, item.model)
        assignments = values.assignments.model_dump()
        if set(assignments.values()) - models.keys():
            raise ValueError("任务分工引用了未配置的模型，请重新选择。")
        return ModelConfiguration(models, assignments)

    def save(self, settings):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"models": [{"id": mid, **asdict(s)} for mid, s in settings.models.items()],
                "assignments": settings.assignments}
        fd, name = tempfile.mkstemp(prefix="provider-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(body, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
