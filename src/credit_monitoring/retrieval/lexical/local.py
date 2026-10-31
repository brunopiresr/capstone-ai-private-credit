"""Complete local Markdown retrieval; owns chunking, index identity, and reuse."""

import hashlib
import json
from typing import Any

from credit_monitoring.retrieval.lexical.sec import build_index, search


class LocalEvidenceSearch:
    """Retain one content/metadata-addressed lexical index, without source I/O."""

    def __init__(self) -> None:
        self._key: str | None = None
        self._index = None
        self._chunk_count = 0

    def clear(self) -> None:
        self._key, self._index, self._chunk_count = None, None, 0

    def rebuild(self, documents: list[dict[str, Any]]) -> int:
        """Build a replacement first so an indexing error retains the prior index."""
        replacement = type(self)()
        replacement.search(documents, "covenant")
        self._key = replacement._key
        self._index = replacement._index
        self._chunk_count = replacement._chunk_count
        return self._chunk_count

    def search(
        self, documents: list[dict[str, Any]], query: str, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        key = hashlib.sha256(
            json.dumps(documents, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if key != self._key:
            chunks = []
            for document in documents:
                text = document["content"]
                for start in range(0, len(text), 3000):
                    end = min(start + 3500, len(text))
                    chunks.append(
                        {
                            **document,
                            "content": text[start:end],
                            "source_start": start,
                            "source_end": end,
                        }
                    )
            self._index = build_index(chunks)
            self._chunk_count = len(chunks)
            self._key = key
        return search(query, index=self._index, document_count=self._chunk_count, ticker=ticker)[
            :10
        ]
