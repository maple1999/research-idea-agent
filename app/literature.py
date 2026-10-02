import asyncio
import hashlib
import time

import httpx
from defusedxml import ElementTree


class Literature:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport
        self.lock = asyncio.Lock()
        self.last_request = 0.0

    async def search(self, query, timeout=30):
        query = query.strip()[:300]
        key = "arxiv:" + query.casefold()
        cached = self.store.cached(key)
        if cached is not None:
            return cached, "cache"
        async with self.lock:
            await asyncio.sleep(max(0, 3 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            async with httpx.AsyncClient(transport=self.transport, timeout=timeout) as client:
                response = await client.get("https://export.arxiv.org/api/query", params={
                    "search_query": "all:" + query, "start": 0, "max_results": 8,
                    "sortBy": "relevance"}, headers={"User-Agent": "ResearchIdeaAgent/0.1"})
                response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        records = []
        for entry in root.findall("a:entry", ns):
            url = entry.findtext("a:id", default="", namespaces=ns).replace("http://", "https://")
            if not url.startswith("https://arxiv.org/abs/"):
                continue
            records.append({"id": "src_" + hashlib.sha256(url.encode()).hexdigest()[:16],
                            "title": " ".join(entry.findtext("a:title", default="", namespaces=ns).split()),
                            "text": entry.findtext("a:summary", default="", namespaces=ns).strip(),
                            "url": url, "kind": "abstract", "locator": "arXiv abstract",
                            "published": entry.findtext("a:published", default="", namespaces=ns)})
        self.store.cache(key, records)
        return records, "arxiv"
