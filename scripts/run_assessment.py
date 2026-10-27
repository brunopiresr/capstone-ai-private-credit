"""Run an assessment using existing financial storage and synthetic covenant inputs."""

import argparse
from datetime import date
from pathlib import Path

import logfire
from dotenv import load_dotenv

from credit_monitoring.application.bootstrap import create_assessment_service
from credit_monitoring.config.settings import AssessmentSettings, RiskModelConfig
from credit_monitoring.covenants.structured import SyntheticCovenantReader
from credit_monitoring.financials.repositories import FinancialRepository
from credit_monitoring.observability import configure_observability
from credit_monitoring.observability.logging import configure_logging
from credit_monitoring.paths import APP_SYNTHETIC_DIR, ROOT, RUNTIME_DIR


def main() -> None:
    """Print a typed assessment; ML remains disabled unless explicitly requested."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--borrower-id", required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--information-cutoff", type=date.fromisoformat, required=True)
    parser.add_argument("--financial-db", type=Path, default=RUNTIME_DIR / "financials.sqlite3")
    parser.add_argument("--analytics-db", type=Path, default=RUNTIME_DIR / "analytics.sqlite3")
    parser.add_argument(
        "--terms", type=Path, default=APP_SYNTHETIC_DIR / "synthetic_covenant_terms.csv"
    )
    parser.add_argument("--ml", action="store_true", help="Enable the configured risk model.")
    parser.add_argument(
        "--model-type", default="stub", help="Model type: stub or logistic_regression."
    )
    parser.add_argument("--model-version", default="v1")
    parser.add_argument("--model-artifact", type=Path, help="Local trained-artifact directory.")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Enable package logs on stderr; INFO shows calculation inputs and results.",
    )
    arguments = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    configure_observability()
    if arguments.log_level is not None:
        configure_logging(arguments.log_level)
    try:
        service = create_assessment_service(
            financial_repository=FinancialRepository(arguments.financial_db),
            covenant_reader=SyntheticCovenantReader(arguments.terms),
            settings=AssessmentSettings(
                analytics_database=arguments.analytics_db,
                risk_model=RiskModelConfig(
                    type=arguments.model_type,
                    version=arguments.model_version,
                    artifact_path=arguments.model_artifact,
                ),
            ),
        )
        assessment = service.assess(
            arguments.borrower_id,
            arguments.period_end,
            arguments.information_cutoff,
            ml_enabled=arguments.ml,
        )
        print(assessment.model_dump_json(indent=2))
    finally:
        logfire.force_flush(timeout_millis=3000)


if __name__ == "__main__":
    main()
