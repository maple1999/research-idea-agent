"""Local provider overrides; never included in project exports or event payloads."""
import json
import os
import tempfile
from dataclasses import asdict

from .models import ProviderInput
from .provider import Settings


class Configuration:
    def __init__(self, directory):
        self.path = directory / "provider-settings.json"

    def load(self, default):
        if not self.path.exists():
            return default
        try:
            values = ProviderInput.model_validate_json(self.path.read_text(encoding="utf-8"))
            return self.resolve(values, default)
        except (ValueError, OSError):
            raise RuntimeError("本地模型配置无法读取，请检查 data/provider-settings.json。") from None

    def resolve(self, values, previous):
        endpoint = str(values.api_base).rstrip("/")
        key = values.api_key.get_secret_value().strip() if values.api_key else ""
        if not key and endpoint != previous.api_base.rstrip("/"):
            raise ValueError("更换 API 地址时请填写该服务的密钥。")
        key = key or previous.api_key
        if not key:
            raise ValueError("请填写 API 密钥。")
        return Settings(endpoint, key, values.model, values.output_mode,
                        values.token_parameter, values.max_output)

    def save(self, settings):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="provider-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(asdict(settings), file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
