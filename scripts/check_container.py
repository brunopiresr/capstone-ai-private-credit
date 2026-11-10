"""Check the running image, bundled ML assessment, pages, and volume persistence."""

import argparse
import csv
import json
import os
from datetime import date
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-saved",
        action="store_true",
        help="Read the previous run after container recreation.",
    )
    arguments = parser.parse_args()

    # This check exercises local code and data without calling optional providers.
    os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
    os.environ.pop("OPENAI_API_KEY", None)

    from streamlit.testing.v1 import AppTest

    from credit_monitoring.application.bootstrap import create_portfolio_service
    from credit_monitoring.paths import DATA_ROOT, ROOT, RUNTIME_DIR, SEC_CATALOG

    with urlopen("http://127.0.0.1:8501/_stcore/health", timeout=5) as response:
        assert response.status == 200, "Streamlit health endpoint failed."

    service = create_portfolio_service(data_root=DATA_ROOT, working_dir=RUNTIME_DIR / "portfolio")
    assert len(service.borrowers) == 37, "Bundled borrowers are missing."
    with SEC_CATALOG.open(newline="", encoding="utf-8") as source:
        assert len(list(csv.DictReader(source))) == 69, "Bundled source catalog is missing."

    saved_path = RUNTIME_DIR / "container-check.json"
    cache_marker = DATA_ROOT / "cache" / "sec" / ".container-check"
    if arguments.verify_saved:
        saved = json.loads(saved_path.read_text())
        assessment = service.repository.get_assessment(saved["assessment_run_id"])
        assert cache_marker.read_text() == assessment.assessment_run_id, (
            "SEC cache did not persist."
        )
    else:
        outcomes = service.assess(
            ["SYN002"], period_end=date(2025, 9, 30), cutoff=date(2025, 9, 30)
        )
        assert len(outcomes) == 1 and outcomes[0].error is None, outcomes
        assessment = outcomes[0].assessment
        assert assessment is not None
        saved_path.write_text(
            json.dumps({"assessment_run_id": assessment.assessment_run_id}) + "\n"
        )
        cache_marker.parent.mkdir(parents=True, exist_ok=True)
        cache_marker.write_text(assessment.assessment_run_id)

    assert assessment.verification.is_valid, assessment.verification
    assert assessment.results, "No covenant calculations were produced."
    prediction = assessment.prediction
    assert prediction is not None, "No bundled model prediction was produced."
    assert prediction.model_name == "logistic_regression", prediction
    assert prediction.prediction_status == "complete", prediction
    assert prediction.breach_probability is not None, prediction

    # A healthy HTTP server alone does not prove that the Streamlit pages execute.
    app = AppTest.from_file(str(ROOT / "src/credit_monitoring/web/preview.py"), default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert len(app.dataframe[0].value) == 37, "Portfolio page did not load the bundled borrowers."
    for page in (
        "Borrower analysis",
        "Documents & data",
        "Risk review",
        "Board report",
        "User guide",
    ):
        app.radio(key="preview_page").set_value(page).run()
        assert not app.exception, (page, app.exception)

    assert not Path("/app/.env").exists(), "Credentials must not be baked into the image."
    print(
        json.dumps(
            {
                "status": "passed",
                "saved_data_verified": arguments.verify_saved,
                "borrowers": len(service.borrowers),
                "assessment_run_id": assessment.assessment_run_id,
                "model": prediction.model_name,
                "pages_checked": 6,
            }
        )
    )


if __name__ == "__main__":
    main()
