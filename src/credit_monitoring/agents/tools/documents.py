"""Allowlisted document tools with strict arguments and application-owned configuration."""

import json
import sqlite3
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.covenants.extraction import ExtractionError


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ListArguments(ToolArguments):
    ticker: str | None = Field(default=None, description="Restrict to a catalog ticker, or null.")


class DocumentArguments(ToolArguments):
    document_id: str = Field(min_length=1, description="Exact catalog document ID.")


class SearchArguments(ListArguments):
    query: str = Field(min_length=1, description="Question or terms to search in source passages.")


_TOOLS = {
    "list_documents": (ListArguments, "List catalog documents and current processing states."),
    "get_document_extraction": (
        DocumentArguments,
        "Read stored facts; report missing/stale state.",
    ),
    "search_evidence": (
        SearchArguments,
        "Retrieve cited filing passages without generating an answer.",
    ),
    "process_document": (
        DocumentArguments,
        "Extract all document facts, reusing a successful cache.",
    ),
}


class DocumentTools:
    def __init__(self, service: DocumentProcessingService, *, ticker: str | None = None) -> None:
        self.service = service
        self.ticker = ticker

    @property
    def definitions(self) -> list[dict]:
        definitions = []
        for name, (model, description) in _TOOLS.items():
            schema = model.model_json_schema()
            schema["required"] = list(schema["properties"])
            for field in schema["properties"].values():
                field.pop("default", None)
            definitions.append(
                {
                    "type": "function",
                    "name": name,
                    "description": description,
                    "parameters": schema,
                    "strict": True,
                }
            )
        return definitions

    def execute(self, name: str, arguments: Any) -> dict:
        if name not in _TOOLS:
            return {"ok": False, "error": "unknown_tool", "message": f"Unknown tool: {name}"}
        try:
            args = _TOOLS[name][0].model_validate(arguments).model_dump()
        except ValidationError as exc:
            return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
        try:
            if "ticker" in args:
                if self.ticker and args["ticker"] not in (None, self.ticker):
                    raise ValueError("Tool ticker is outside the requested issuer scope.")
                args["ticker"] = self.ticker or args["ticker"]
            if "document_id" in args and self.ticker:
                record = self.service.catalog_record(args["document_id"])
                if record.get("ticker") != self.ticker:
                    raise ValueError("Document is outside the requested issuer scope.")
            sources = []
            if name == "list_documents":
                documents = self.service.list_document_extractions(**args, include_results=False)
                data = [d.model_dump(mode="json", exclude={"result"}) for d in documents]
            elif name == "search_evidence":
                records = self.service.search_evidence(**args)
                data = records
                sources = [
                    {"document_id": r["document_id"], "citation": r["citation"]} for r in records
                ]
            else:
                method = getattr(self.service, name)
                document = method(**args)
                data = document.model_dump(mode="json")
                if document.status == "complete":
                    sources = [{"document_id": document.document_id, "citation": document.citation}]
            return {"ok": True, "data": data, "sources": sources}
        except (
            ExtractionError,
            OSError,
            ValueError,
            sqlite3.Error,
            requests.RequestException,
        ) as exc:
            return {"ok": False, "error": "service_error", "message": str(exc)}


def decode_arguments(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except TypeError, json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
