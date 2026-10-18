"""Compose the synthetic working assessment without benchmark outcome inputs."""

import csv
import os
from pathlib import Path

from credit_monitoring.agents.conversation import AgentConversation
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.assessment_service import AssessmentService
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.domain.agent import AgentAnswer
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.ingestion.loaders.financials import load_financials

DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[3] / "data"
DEFAULT_WORKSPACE_DIR = DEFAULT_DATA_ROOT / "processed" / "streamlit"
PREDICTION_MODES = ("Off", "Stub", "Logistic Regression")


class SyntheticWorkspace:
    """Initialize local financial storage; construct separate services for each review."""

    def __init__(self, data_root: Path, working_dir: Path) -> None:
        self.data_root = Path(data_root)
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        database = self.working_dir / "financials.sqlite3"
        load_financials(self.data_root / "synthetic_quarterly_financials.csv", database)
        self.financial_repository = FinancialRepository(database)
        with (self.data_root / "synthetic_borrowers.csv").open(newline="", encoding="utf-8") as f:
            self.borrowers = sorted(
                (
                    {key: row[key] for key in ("borrower_id", "borrower_name", "industry")}
                    for row in csv.DictReader(f)
                    if self.financial_repository.get_history(row["borrower_id"])
                ),
                key=lambda row: row["borrower_name"],
            )

    def periods(self, borrower_id: str) -> list[str]:
        return [row["period_end"] for row in self.financial_repository.get_history(borrower_id)]

    def assessment_service(self, prediction_mode: str) -> AssessmentService:
        if prediction_mode not in PREDICTION_MODES:
            raise ValueError("Unknown prediction mode.")
        model = RiskModelConfig()
        if prediction_mode == "Logistic Regression":
            model = RiskModelConfig(
                type="logistic_regression",
                artifact_path=self.data_root / "models" / "logistic_regression" / "v1",
            )
        return AssessmentService(
            financial_repository=self.financial_repository,
            covenant_reader=SyntheticCovenantReader(
                self.data_root / "synthetic_covenant_terms.csv"
            ),
            settings=AssessmentSettings(
                analytics_database=self.working_dir / "analytics.sqlite3",
                ml_enabled=prediction_mode != "Off",
                risk_model=model,
            ),
        )


def create_conversation(service: AssessmentService, borrower_id: str) -> AgentConversation:
    """Create session-owned memory with only borrower-scoped assessment tools."""
    return CreditAssessmentAgent(
        assessment_service=service, model=os.getenv("LLM_MODEL") or DEFAULT_MODEL
    ).start_conversation(borrower_id=borrower_id)


def ask_about_assessment(
    conversation: AgentConversation, question: str, assessment: RiskAssessment
) -> AgentAnswer | None:
    """Supply selected dates explicitly; the agent obtains facts through its tools."""
    if question.strip().casefold() in {"close", "done", "quit"}:
        return conversation.ask(question)
    return conversation.ask(
        f"The analyst selected borrower {assessment.borrower_id}, reporting period "
        f"{assessment.period_end.isoformat()}, and information cutoff "
        f"{assessment.information_cutoff.isoformat()} for this review. "
        "Use these dates for the review; ask the analyst to change the selection for other dates.\n"
        f"Question: {question}"
    )
