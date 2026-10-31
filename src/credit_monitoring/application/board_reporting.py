"""Build complete flagged registers and persist immutable draft/final report versions."""

import hashlib
import json
from datetime import date

from credit_monitoring.application.manager_workflow import ManagerWorkflow


def signature(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class BoardReporting:
    def __init__(self, manager: ManagerWorkflow):
        self.manager = manager
        self.repository = manager.repository

    def sources(self, period: date, cutoff: date) -> dict:
        if cutoff < period:
            raise ValueError("Information cutoff must be on or after the reporting period.")
        portfolio = self.manager.portfolio
        entries = portfolio.snapshot(period_end=period, cutoff=cutoff)
        flags = self.manager.active_flags(period=period)
        assessments = {}
        # Input order breaks ties by saved run order; the highest period/cutoff wins.
        for assessment in portfolio.repository.all_assessments():
            if assessment.period_end > period or assessment.information_cutoff > cutoff:
                continue
            previous = assessments.get(assessment.borrower_id)
            if previous is None or (assessment.period_end, assessment.information_cutoff) >= (
                previous.period_end,
                previous.information_cutoff,
            ):
                assessments[assessment.borrower_id] = assessment
        untriaged = []
        all_flags = self.repository.flags()
        for borrower, assessment in assessments.items():
            if not any(r.compliance_status == "breach" for r in assessment.results):
                continue
            submitted = [
                s
                for s in self.repository.submissions(borrower)
                if s["run_id"] == assessment.assessment_run_id
            ]
            if not any(f["run_id"] == assessment.assessment_run_id for f in all_flags) and not any(
                s["payload"]["triage"] for s in submitted
            ):
                untriaged.append(borrower)
        selected = {f["borrower_id"] for f in flags} | set(untriaged)
        names = {b["borrower_id"]: b["borrower_name"] for b in portfolio.borrowers}
        items = []
        for borrower in sorted(selected):
            assessment = assessments.get(borrower)
            submission = next(
                (
                    s
                    for s in self.repository.submissions(borrower)
                    if assessment and s["run_id"] == assessment.assessment_run_id
                ),
                None,
            )
            review = (
                next(
                    (
                        r
                        for r in portfolio.repository.review_history(assessment.assessment_run_id)
                        if (r.snapshot.review_information_cutoff or r.snapshot.information_cutoff)
                        <= cutoff
                    ),
                    None,
                )
                if assessment
                else None
            )
            note = self.manager.reviewed_note(submission, review) if submission else None
            requests = self.repository.requests(borrower)
            needs_review = bool(
                assessment and self.manager.analyst.needs_review(assessment.assessment_run_id)
            )
            pending = any(r["state"] not in {"accepted", "cancelled"} for r in requests)
            status = (
                "Changes requested"
                if pending
                else "Sources changed"
                if needs_review
                else "Reviewed"
                if note
                else "Pending review"
                if submission
                else "Analyst submission pending"
            )
            if pending or needs_review:
                note = None
            elif note and self.manager.state(submission) != "Reviewed":
                status = self.manager.state(submission)
                note = None
            borrower_flags = []
            for flag in flags:
                if flag["borrower_id"] == borrower:
                    original = portfolio.repository.get_assessment(flag["run_id"])
                    borrower_flags.append(
                        {
                            **flag,
                            "assessment_period": original.period_end.isoformat(),
                            "assessment_cutoff": original.information_cutoff.isoformat(),
                        }
                    )
            items.append(
                {
                    "borrower_id": borrower,
                    "name": names.get(borrower, borrower),
                    "assessment": assessment.model_dump(mode="json") if assessment else None,
                    "assessment_created_at": portfolio.repository.assessment_created_at(
                        assessment.assessment_run_id
                    )
                    if assessment
                    else None,
                    "flags": borrower_flags,
                    "untriaged_breach": borrower in untriaged,
                    "submission": submission,
                    "review": review.model_dump(mode="json") if review else None,
                    "manager_note": note,
                    "review_state": status,
                    "requests": requests,
                    "notes": self.repository.notes(borrower),
                    "recommendation": note["payload"]["recommendation"]
                    if note
                    else "Pending manager review",
                }
            )
        pending_submissions = []
        for borrower in names:
            latest = self.manager.latest_submission(borrower, period=period, cutoff=cutoff)
            if latest and self.manager.state(latest) != "Reviewed":
                pending_submissions.append(
                    {
                        "borrower_id": borrower,
                        "name": names[borrower],
                        "submission_id": latest["submission_id"],
                        "run_id": latest["run_id"],
                        "period": latest["payload"]["assessment"]["period_end"],
                        "state": self.manager.state(latest),
                    }
                )
        pending_ids = {p["borrower_id"] for p in pending_submissions} | {
            item["borrower_id"] for item in items if item["review_state"] != "Reviewed"
        }
        metrics = {
            "borrowers": len(entries),
            "assessed": sum(e.assessment is not None for e in entries),
            "unassessed": sum(e.assessment is None for e in entries),
            "breaches": sum("breach" in e.statuses for e in entries),
            "data_gaps": sum(e.needs_data for e in entries),
            "flagged_borrowers": len({f["borrower_id"] for f in flags}),
            "untriaged_breaches": len(untriaged),
            "pending_reviews": len(pending_ids),
            "missing_credit_analysis": sum(
                not item["review"] or item["review"]["status"] != "complete" for item in items
            ),
        }
        return {
            "period": period.isoformat(),
            "cutoff": cutoff.isoformat(),
            "metrics": metrics,
            "portfolio": [
                {
                    "borrower_id": e.borrower_id,
                    "period": e.period_end.isoformat(),
                    "compliance": e.compliance,
                    "needs_review": e.needs_review,
                }
                for e in entries
            ],
            "items": items,
            "pending_submissions": pending_submissions,
        }

    def generate(
        self, period: date, cutoff: date, *, title: str = "Quarterly credit risk review"
    ) -> str:
        if not title.strip():
            raise ValueError("Supply a board report title.")
        sources = self.sources(period, cutoff)
        metrics = sources["metrics"]
        summary = (
            f"{metrics['flagged_borrowers']} flagged borrowers and "
            f"{metrics['untriaged_breaches']} untriaged breaches require attention. "
            f"{metrics['pending_reviews']} cases await completed review; "
            f"{metrics['unassessed']} borrowers are not assessed for this reporting period."
        )
        return self.repository.save_board_report(
            {
                "title": title.strip(),
                "summary": summary,
                "sources": sources,
                "source_signature": signature(sources),
                "recommendations": {},
            },
            state="draft",
        )

    def save(
        self,
        report_id: str,
        *,
        title: str,
        summary: str,
        recommendations: dict[str, str],
        finalize: bool = False,
        refresh: bool = False,
    ) -> str:
        previous = self.repository.board_report(report_id)
        if previous["state"] == "final":
            raise ValueError("Final reports are frozen. Generate a new report to make changes.")
        if not title.strip() or not summary.strip():
            raise ValueError("Supply a title and executive summary.")
        payload = previous["payload"]
        old_sources = payload["sources"]
        current = self.sources(
            date.fromisoformat(old_sources["period"]), date.fromisoformat(old_sources["cutoff"])
        )
        if finalize and signature(current) != payload["source_signature"]:
            raise ValueError(
                "Report sources changed. Refresh the draft sources "
                "and inspect them before finalizing."
            )
        sources = current if refresh else old_sources
        ids = {item["borrower_id"] for item in sources["items"]}
        return self.repository.save_board_report(
            {
                "title": title.strip(),
                "summary": summary.strip(),
                "sources": sources,
                "source_signature": signature(sources),
                "recommendations": {
                    bid: text.strip() for bid, text in recommendations.items() if bid in ids
                },
            },
            state="final" if finalize else "draft",
            parent_id=report_id,
        )
