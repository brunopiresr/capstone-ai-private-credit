"""Local working catalog and extraction model boundary for connected source tests."""

import csv

from model_helpers import ScriptedModel, model_response
from portfolio_helpers import portfolio_inputs

from credit_monitoring.application.bootstrap import (
    create_document_service,
    create_portfolio_service,
)
from credit_monitoring.application.document_workspace import PROCESS_ID, DocumentWorkspace
from credit_monitoring.domain import CovenantExtraction
from credit_monitoring.ingestion.converters.sec_markdown import CONVERSION_VERSION
from credit_monitoring.persistence.document_workspace_repository import DocumentWorkspaceRepository
from credit_monitoring.persistence.workflow_repository import WorkflowRepository


def document_inputs(tmp_path):
    root = portfolio_inputs(tmp_path)
    record = {
        "document_id": "DOC_ONE",
        "company": "Harbor Components",
        "ticker": "SYN001",
        "document_type": "Amendment",
        "document_date": "2025-02-03",
        "source_url": "https://example.invalid/one.html",
    }
    with (root / "app/sec/public_sec_documents.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(record))
        writer.writeheader()
        writer.writerows(
            [
                record,
                {
                    **record,
                    "document_id": "DOC_TWO",
                    "source_url": "https://example.invalid/two.html",
                },
            ]
        )
    return root


def local_markdown(workspace, document_id="DOC_ONE", text="Maximum leverage covenant is 4.0x."):
    folder = workspace.processor.markdown_dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{document_id}.md").write_text(text)
    (folder / f".{document_id}.conversion-version").write_text(CONVERSION_VERSION)


def document_workspace(tmp_path, **processor_options):
    root = document_inputs(tmp_path)
    working = tmp_path / "working"
    model = ScriptedModel(model_name="documents-offline")
    model.respond.return_value = model_response(extraction=CovenantExtraction())
    portfolio = create_portfolio_service(data_root=root, working_dir=working)
    processor = create_document_service(
        source_file=working / "documents/catalog.csv",
        html_dir=root / "cache/sec/html",
        markdown_dir=root / "cache/sec/markdown",
        database_path=working / "documents/extractions.sqlite3",
        model=model,
        user_agent="Offline Test test@example.invalid",
        **processor_options,
    )
    workspace = DocumentWorkspace(
        portfolio=portfolio,
        processor=processor,
        data_root=root,
        working_dir=working,
        workflow=WorkflowRepository(working / "workflow.sqlite3"),
        repository=DocumentWorkspaceRepository(working / "workflow.sqlite3", process_id=PROCESS_ID),
    )
    return workspace, model
