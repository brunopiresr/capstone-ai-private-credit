"""Version-bound manager decisions and analyst requests over saved submissions."""

import threading
from datetime import date

from credit_monitoring.application.borrower_workflow import BorrowerWorkflow
from credit_monitoring.domain.analytics_base import utc_now
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.credit_review import (
    AdditionalReviewContext,
    CreditReviewResult,
    ExposureDecisionContext,
)

REVIEW_LOCK = threading.Lock()
DEFAULT_CRITERIA = (
    "Assess covenant compliance, headroom and data limitations.",
    "Weigh both perspectives before recommending an action for the exposure.",
)


class ManagerWorkflow:
    def __init__(self, analyst: BorrowerWorkflow):
        self.analyst = analyst
        self.portfolio = analyst.portfolio
        self.repository = analyst.repository

    @staticmethod
    def assessment(submission: dict) -> RiskAssessment:
        return RiskAssessment.model_validate(submission["payload"]["assessment"])

    def latest_submission(
        self,
        borrower_id: str,
        *,
        period: date | None = None,
        cutoff: date | None = None,
        exact_period: bool = False,
    ) -> dict | None:
        for submission in self.repository.submissions(borrower_id):
            assessment = self.assessment(submission)
            if period and (
                assessment.period_end != period if exact_period else assessment.period_end > period
            ):
                continue
            if cutoff and assessment.information_cutoff > cutoff:
                continue
            return submission
        return None

    def active_flags(
        self, borrower_id: str | None = None, *, period: date | None = None
    ) -> list[dict]:
        return [
            f
            for f in self.repository.flags(borrower_id)
            if f["payload"]["state"] == "open"
            and (
                not period
                or self.portfolio.repository.get_assessment(f["run_id"]).period_end <= period
            )
        ]

    def current_review(
        self, submission: dict, *, cutoff: date | None = None
    ) -> CreditReviewResult | None:
        return next(
            (
                r
                for r in self.portfolio.repository.review_history(submission["run_id"])
                if cutoff is None
                or (r.snapshot.review_information_cutoff or r.snapshot.information_cutoff) <= cutoff
            ),
            None,
        )

    def reviewed_note(self, submission: dict, review: CreditReviewResult | None) -> dict | None:
        return next(
            (
                n
                for n in self.repository.notes(submission["borrower_id"])
                if n["submission_id"] == submission["submission_id"]
                and n["payload"]["state"] == "reviewed"
                and n["payload"]["review_id"] == (review.review_id if review else None)
            ),
            None,
        )

    def pending_requests(self, borrower_id: str) -> list[dict]:
        return [
            r
            for r in self.repository.requests(borrower_id)
            if r["state"] not in {"accepted", "cancelled"}
        ]

    def state(self, submission: dict) -> str:
        if self.pending_requests(submission["borrower_id"]):
            return "Changes requested"
        if self.analyst.needs_review(submission["run_id"]):
            return "Sources changed"
        assessment = self.assessment(submission)
        latest = self.latest_submission(
            assessment.borrower_id, period=assessment.period_end, exact_period=True
        )
        if latest and latest["submission_id"] != submission["submission_id"]:
            return "Superseded submission"
        latest_run = self.portfolio.repository.latest_assessment(
            assessment.borrower_id, assessment.period_end, date.max
        )
        if latest_run and latest_run[0].assessment_run_id != submission["run_id"]:
            return "Reassessment awaiting submission"
        submitted_flags = {f["flag_id"] for f in submission["payload"]["flags"]}
        if any(
            f["flag_id"] not in submitted_flags
            for f in self.active_flags(assessment.borrower_id)
            if self.portfolio.repository.get_assessment(f["run_id"]).period_end
            == assessment.period_end
        ):
            return "New flags awaiting submission"
        return (
            "Reviewed"
            if self.reviewed_note(submission, self.current_review(submission))
            else "Pending review"
        )

    def record_note(
        self,
        submission_id: str,
        *,
        comment: str,
        recommendation: str = "",
        manager: str = "",
        reviewed: bool = False,
        disposition: str = "Continue monitoring",
        resolve_ids: list[str] = (),
    ) -> str:
        submission = self.repository.submission(submission_id)
        if not comment.strip() and not recommendation.strip():
            raise ValueError("Add a manager observation or recommendation.")
        if disposition not in {
            "Continue monitoring",
            "Request remediation",
            "Resolve selected flags",
        }:
            raise ValueError("Choose a supported manager disposition.")
        if reviewed:
            if not recommendation.strip():
                raise ValueError("Add a recommendation before marking the case reviewed.")
            if self.state(submission) not in {"Pending review", "Reviewed"}:
                raise ValueError(
                    "Resolve outstanding requests, source changes and newer submissions "
                    "before completing review."
                )
        if resolve_ids:
            allowed = {f["flag_id"] for f in submission["payload"]["flags"]}
            if (
                not reviewed
                or disposition != "Resolve selected flags"
                or set(resolve_ids) - allowed
            ):
                raise ValueError(
                    "Resolve only flags covered by this submitted report and completed review."
                )
        if reviewed and disposition == "Resolve selected flags" and not resolve_ids:
            raise ValueError("Select the flags to resolve.")
        review = self.current_review(submission)
        return self.repository.note(
            submission,
            {
                "comment": comment.strip(),
                "recommendation": recommendation.strip(),
                "manager": manager.strip(),
                "state": "reviewed" if reviewed else "comment",
                "disposition": disposition,
                "resolved_flag_ids": list(resolve_ids),
                "review_id": review.review_id if review else None,
                "review": review.model_dump(mode="json") if review else None,
            },
            resolve_ids=list(resolve_ids),
        )

    def request_analysis(
        self,
        submission_id: str,
        *,
        kind: str,
        question: str,
        context: str = "",
        source: str = "",
        available_at: date | None = None,
        review_cutoff: date | None = None,
        owner: str = "",
        due: date | None = None,
        criteria: tuple[str, ...] = DEFAULT_CRITERIA,
    ) -> str:
        submission = self.repository.submission(submission_id)
        assessment = self.assessment(submission)
        if kind not in {"context", "correction"} or not question.strip():
            raise ValueError("Choose a request type and supply the analysis question.")
        cutoff = review_cutoff or assessment.information_cutoff
        if cutoff < assessment.information_cutoff or (available_at and available_at > cutoff):
            raise ValueError("Update the review cutoff to include the additional information date.")
        if not criteria or any(not c.strip() for c in criteria):
            raise ValueError("Supply at least one credit criterion.")
        review = self.current_review(submission)
        return self.repository.add_request(
            submission,
            {
                "kind": kind,
                "question": question.strip(),
                "context": context.strip(),
                "source": source.strip(),
                "available_at": available_at.isoformat() if available_at else None,
                "review_cutoff": cutoff.isoformat(),
                "owner": owner.strip(),
                "due": due.isoformat() if due else None,
                "criteria": list(criteria),
                "previous_review_id": review.review_id if review else None,
                "review_id": None,
                "response": "",
                "fulfillment_submission_id": None,
                "attempts": [],
            },
        )

    def run_requested_review(self, request_id: str) -> CreditReviewResult:
        if not REVIEW_LOCK.acquire(blocking=False):
            raise ValueError("Another requested credit review is running. Wait for it to finish.")
        try:
            request = self.repository.request(request_id)
            item = request["payload"]
            if request["state"] != "open" or item["kind"] != "context":
                raise ValueError("Only an open context request can run a supplementary review.")
            if self.analyst.needs_review(request["run_id"]):
                raise ValueError("Sources changed. Return to the analyst for reassessment first.")
            context = (
                (
                    AdditionalReviewContext(
                        statement=item["context"],
                        source=item["source"] or None,
                        available_at=date.fromisoformat(item["available_at"])
                        if item["available_at"]
                        else None,
                    ),
                )
                if item["context"]
                else ()
            )
            try:
                review = self.portfolio.review_service.review_assessment(
                    self.portfolio.repository.get_assessment(request["run_id"]),
                    decision_context=ExposureDecisionContext(
                        question=item["question"], credit_criteria=tuple(item["criteria"])
                    ),
                    additional_context=context,
                    review_cutoff=date.fromisoformat(item["review_cutoff"]),
                )
                self.portfolio.repository.save_review(review)
                self.portfolio.generate_follow_ups(
                    self.portfolio.repository.get_assessment(request["run_id"]), review
                )
            except Exception as error:
                payload = {**item, "last_error": f"Credit review failed ({type(error).__name__})."}
                self.repository.update_request(request, "open", payload)
                raise ValueError(payload["last_error"]) from error
            payload = {
                **item,
                "review_id": review.review_id,
                "attempts": [*item["attempts"], review.review_id],
                "response": "Supplementary review completed."
                if review.status == "complete"
                else "",
                "last_error": None
                if review.status == "complete"
                else "Review incomplete; retry explicitly.",
            }
            self.repository.update_request(
                request, "response_ready" if review.status == "complete" else "open", payload
            )
            return review
        finally:
            REVIEW_LOCK.release()

    def respond(self, request_id: str, *, response: str, submission_id: str | None = None) -> None:
        request = self.repository.request(request_id)
        item = request["payload"]
        if request["state"] in {"accepted", "cancelled"} or not response.strip():
            raise ValueError("Supply a response to an outstanding request.")
        if item["kind"] == "correction":
            if not submission_id:
                raise ValueError("Select the new validated analyst submission.")
            submitted = self.repository.submission(submission_id)
            assessment, original = (
                self.assessment(submitted),
                self.portfolio.repository.get_assessment(request["run_id"]),
            )
            if (
                submitted["borrower_id"] != request["borrower_id"]
                or assessment.period_end != original.period_end
                or submitted["run_id"] == request["run_id"]
                or submitted["created_at"] <= request["created_at"]
                or self.portfolio.repository.assessment_created_at(submitted["run_id"])
                <= request["created_at"]
                or assessment.information_cutoff < date.fromisoformat(item["review_cutoff"])
                or self.analyst.needs_review(submitted["run_id"])
            ):
                raise ValueError(
                    "Recalculate, validate and submit this borrower-period after the request, "
                    "using the required cutoff."
                )
        elif (
            not item["review_id"]
            or self.portfolio.repository.get_review(item["review_id"]).status != "complete"
        ):
            raise ValueError("Run the requested supplementary review before responding.")
        self.repository.update_request(
            request,
            "response_ready",
            {
                **item,
                "response": response.strip(),
                "fulfillment_submission_id": submission_id,
                "responded_at": utc_now().isoformat(),
            },
        )

    def accept_response(self, request_id: str, *, manager: str = "") -> None:
        request = self.repository.request(request_id)
        if request["state"] != "response_ready":
            raise ValueError("Review a completed response before accepting it.")
        if request["payload"]["kind"] == "correction":
            submitted = self.repository.submission(request["payload"]["fulfillment_submission_id"])
            if self.analyst.needs_review(submitted["run_id"]):
                raise ValueError("Sources changed after the response. Reassessment is required.")
        self.repository.update_request(
            request,
            "accepted",
            {
                **request["payload"],
                "accepted_by": manager.strip(),
                "accepted_at": utc_now().isoformat(),
            },
        )

    def cancel_request(self, request_id: str, *, reason: str, manager: str = "") -> None:
        request = self.repository.request(request_id)
        if request["state"] in {"accepted", "cancelled"} or not reason.strip():
            raise ValueError("Supply a cancellation reason for an outstanding request.")
        self.repository.update_request(
            request,
            "cancelled",
            {
                **request["payload"],
                "cancellation_reason": reason.strip(),
                "cancelled_by": manager.strip(),
                "cancelled_at": utc_now().isoformat(),
            },
        )
