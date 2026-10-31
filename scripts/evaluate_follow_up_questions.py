"""Opt-in generation from saved analyses, with a rubric for human quality scoring."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from credit_monitoring.agents.follow_up_questions import FollowUpQuestionAgent
from credit_monitoring.agents.models import DEFAULT_MODEL
from credit_monitoring.application.follow_up_question_service import analysis_context
from credit_monitoring.paths import ROOT, RUNTIME_DIR
from credit_monitoring.persistence.portfolio_repository import PortfolioRepository

RUBRIC = {
    "relevance": "1: generic; 3: relevant topic; 5: identifies a consequential specific finding.",
    "grounding": "1: invented claim; 3: partly supported; 5: all premises match cited findings.",
    "usefulness": "1: redundant/unanswerable; 3: useful; 5: clarifies a decision or uncertainty.",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--working-dir", type=Path, default=RUNTIME_DIR / "portfolio")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--live", action="store_true", help="Permit billable model requests.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live explicitly to generate questions with provider usage.")
    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        parser.error("Configure OPENAI_API_KEY before running the live evaluation.")
    database = args.working_dir / "portfolio.sqlite3"
    if not database.is_file():
        parser.error("Working portfolio database does not exist.")
    repository = PortfolioRepository(database)
    agent = FollowUpQuestionAgent(args.model or os.getenv("LLM_MODEL") or DEFAULT_MODEL)
    cases = []
    for run_id in args.run_id:
        assessment = repository.get_assessment(run_id)
        # Include earlier reviews: they provide paired cases with identical calculations
        # and differing risk-agent conclusions when the analyst has rerun a review.
        reviews = repository.review_history(run_id) or [None]
        for review in reviews:
            context = analysis_context(assessment, review)
            questions, usage = agent.generate(context)
            cases.append(
                {
                    "context": context,
                    "suggestions": questions.model_dump(mode="json"),
                    "usage": usage,
                    "scores": dict.fromkeys(RUBRIC),
                    "reviewer_notes": "",
                }
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "rubric": RUBRIC,
                "instructions": "Score each dimension 1–5 against the evidence. Compare questions "
                "across review versions with identical calculations. Scores need a human reviewer; "
                "successful generation alone is not a quality pass.",
                "cases": cases,
            },
            indent=2,
        )
    )
    print(f"Generated {len(cases)} evaluation cases at {args.output}. Scores await human review.")


if __name__ == "__main__":
    main()
