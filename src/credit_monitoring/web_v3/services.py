"""Compose shared services without importing a legacy page's navigation or state."""

import os
from dataclasses import dataclass

from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.bootstrap import (
    create_document_service,
    create_portfolio_service,
)
from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.application.document_workspace import PROCESS_ID, DocumentWorkspace
from credit_monitoring.application.manager_workflow import ManagerWorkflow
from credit_monitoring.paths import DATA_ROOT, RUNTIME_DIR
from credit_monitoring.persistence.document_workspace_repository import DocumentWorkspaceRepository
from credit_monitoring.persistence.workflow_repository import WorkflowRepository
from credit_monitoring.web_v3.checklist import ChecklistRepository

WORKING_DIR = RUNTIME_DIR / "portfolio"


@dataclass
class Services:
    analyst: BorrowerWorkflow
    manager: ManagerWorkflow
    documents: DocumentWorkspace
    checklists: ChecklistRepository


def get_services() -> Services:
    model = os.getenv("LLM_MODEL") or DEFAULT_MODEL
    portfolio = create_portfolio_service(data_root=DATA_ROOT, working_dir=WORKING_DIR, model=model)
    repository = WorkflowRepository(WORKING_DIR / "workflow.sqlite3")
    analyst = BorrowerWorkflow(portfolio, repository, DATA_ROOT)
    processor = create_document_service(
        source_file=WORKING_DIR / "documents" / "catalog.csv",
        html_dir=DATA_ROOT / "cache" / "sec" / "html",
        markdown_dir=DATA_ROOT / "cache" / "sec" / "markdown",
        database_path=WORKING_DIR / "documents" / "extractions.sqlite3",
        model=model,
        user_agent=os.getenv("SEC_USER_AGENT", ""),
    )
    documents = DocumentWorkspace(
        portfolio=portfolio,
        processor=processor,
        repository=DocumentWorkspaceRepository(repository.database_path, process_id=PROCESS_ID),
        workflow=repository,
        data_root=DATA_ROOT,
        working_dir=WORKING_DIR,
    )
    return Services(
        analyst, ManagerWorkflow(analyst), documents, ChecklistRepository(repository.database_path)
    )
