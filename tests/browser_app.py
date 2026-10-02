"""Deterministic browser test server. Never imported by the production app."""
import asyncio
from tempfile import TemporaryDirectory

from app.main import create_app
from tests.test_research import EmptyLiterature, FakeProvider


class BrowserFixture(FakeProvider):
    async def generate(self, project, timeout=120):
        await asyncio.sleep(0.5)
        return self.step, 350


test_data = TemporaryDirectory(prefix="idea-browser-test-")
app = create_app(test_data.name, BrowserFixture(), EmptyLiterature)
