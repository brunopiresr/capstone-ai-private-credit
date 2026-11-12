"""One projection drives queue membership, evidence badges and next actions."""

from dataclasses import dataclass
from datetime import date

from credit_monitoring.application.portfolio_service import PortfolioEntry
from credit_monitoring.web_v3.checklist import checklist_states
from credit_monitoring.web_v3.services import Services

FILTERS = (
    "Needs action",
    "Missing documents",
    "Processing needed",
    "Missing financial inputs",
    "Assessment needed / outdated",
    "Validation needed",
    "Manager requests",
    "Ready to submit",
    "Requirements not configured",
    "All borrowers",
)


@dataclass
class Readiness:
    categories: set[str]
    evidence: str
    review: str
    action: str
    section: str
    reasons: list[str]
    validated: bool
    submission: dict | None


def submission_blockers(workflow, assessment, text: str, triage: str) -> list[str]:
    blockers = []
    if not text.strip():
        blockers.append("Add analyst observations.")
    if not workflow.validation(assessment.assessment_run_id):
        blockers.append("Validate the selected assessment and current AI analysis.")
    flags = [
        f
        for f in workflow.repository.flags(assessment.borrower_id)
        if f["run_id"] == assessment.assessment_run_id and f["payload"]["state"] == "open"
    ]
    if (
        any(r.compliance_status == "breach" for r in assessment.results)
        and not flags
        and not triage.strip()
    ):
        blockers.append("Add a flag for this breach version or explain the triage decision.")
    return blockers


def project(
    services: Services, entry: PortfolioEntry, period: date, inventory: list[dict]
) -> Readiness:
    workflow = services.analyst
    assessment = entry.assessment
    items = services.checklists.load(entry.borrower_id, period)
    states = checklist_states(items, entry.borrower_id, inventory)
    linked = [r for r in inventory if entry.borrower_id in r["borrower_ids"]]
    categories, reasons = set(), []
    if items is None:
        evidence = "Requirements not configured"
        categories.add(evidence)
        reasons.append("Define the document checklist for this reporting period.")
    elif any(s["state"] == "Missing attachment" for s in states):
        evidence = "Required documents missing"
        categories.add("Missing documents")
        reasons.append("Attach missing required documents.")
    elif any(s["state"] != "Processed · inspect evidence" for s in states):
        evidence = "Evidence needs attention"
    else:
        evidence = "Checklist evidence processed" if items else "No documents required"
    problem_docs = [r for r in linked if r.get("format_issue") or r["status"] != "complete"]
    if problem_docs:
        categories.add("Processing needed")
        reasons.append("Process linked sources or address unsupported / failed documents.")
        if evidence == "Checklist evidence processed":
            evidence = "Additional evidence needs attention"
    financials = workflow.portfolio.assessment_service.financial_repository.get_period_history(
        entry.borrower_id, as_of=period
    )
    if assessment:
        from credit_monitoring.application.borrower_workflow import SavedFinancials

        financials = SavedFinancials(assessment).get_period_history(entry.borrower_id, as_of=period)
    current = next((f for f in financials if f.period_end == period), None)
    # Optional metrics are legitimately null. Only service-reported input gaps
    # (or an absent financial period) establish missing calculation inputs.
    missing_input = bool(
        assessment
        and any(
            "missing financial input" in issue.casefold()
            or "springing availability is missing" in issue.casefold()
            for result in assessment.results
            for issue in result.issues
        )
    )
    if not current or missing_input:
        categories.add("Missing financial inputs")
        reasons.append("Inspect missing financial inputs in Evidence.")
    if assessment and entry.needs_data and "Missing financial inputs" not in categories:
        reasons.append("Resolve calculation or verification gaps in Evidence.")
    outdated = bool(assessment and workflow.needs_review(assessment.assessment_run_id))
    if not assessment or outdated:
        categories.add("Assessment needed / outdated")
        reasons.append(
            "Sources changed; reassess this borrower." if outdated else "Run a covenant assessment."
        )
    validated = bool(assessment and workflow.validation(assessment.assessment_run_id))
    submission = next(
        (
            s
            for s in workflow.repository.submissions(entry.borrower_id)
            if assessment and s["run_id"] == assessment.assessment_run_id
        ),
        None,
    )
    if assessment and not validated:
        categories.add("Validation needed")
        reasons.append("Complete the analyst evidence checks and validation.")
    requests = services.manager.pending_requests(entry.borrower_id)
    if requests:
        categories.add("Manager requests")
        reasons.insert(0, f"{len(requests)} manager request(s) awaiting completion or acceptance.")
    if validated and not submission:
        records = workflow.repository.events(assessment.assessment_run_id, "draft")
        draft = records[0]["payload"] if records else {}
        if not submission_blockers(
            workflow, assessment, draft.get("text", ""), draft.get("triage", "")
        ):
            categories.add("Ready to submit")
        reasons.append("Review findings and submit to the risk manager.")
    review = (
        services.manager.state(submission)
        if submission
        else "Validated"
        if validated
        else "Analyst review needed"
    )
    if submission and not requests and not outdated and validated:
        reasons.append(f"Submitted · {review}")
    if requests:
        action, section = "Respond to manager", "Review and submit"
    elif items is None or "Missing documents" in categories:
        action, section = "Set up documents" if items is None else "Attach documents", "Documents"
    elif problem_docs:
        action, section = "Process documents", "Documents"
    elif "Missing financial inputs" in categories or (assessment and entry.needs_data):
        action, section = "Review inputs", "Evidence"
    elif not assessment or outdated:
        action, section = "Run covenant assessment", "Overview"
    elif not validated or not submission:
        action, section = "Review and submit findings", "Review and submit"
    else:
        action, section = "Open saved findings", "Overview"
    if categories or (assessment and (entry.needs_data or not submission)):
        categories.add("Needs action")
    categories.add("All borrowers")
    return Readiness(categories, evidence, review, action, section, reasons, validated, submission)


def manager_cases(services: Services, period: date, cutoff: date) -> list[dict]:
    """Include submissions and requests even when they have no open flags."""
    manager = services.manager
    cases = []
    for borrower in manager.portfolio.borrowers:
        bid = borrower["borrower_id"]
        submission = manager.latest_submission(bid, period=period, cutoff=cutoff)
        flags = [
            f
            for f in manager.active_flags(bid, period=period)
            if manager.portfolio.repository.get_assessment(f["run_id"]).information_cutoff <= cutoff
        ]
        requests = [
            r
            for r in manager.pending_requests(bid)
            if manager.portfolio.repository.get_assessment(r["run_id"]).period_end <= period
            and manager.portfolio.repository.get_assessment(r["run_id"]).information_cutoff
            <= cutoff
        ]
        history = [
            a
            for a, _ in manager.portfolio.repository.assessment_history(bid)
            if a.period_end <= period and a.information_cutoff <= cutoff
        ]
        assessment = (
            max(history, key=lambda a: (a.period_end, a.information_cutoff)) if history else None
        )
        untriaged = bool(
            assessment
            and any(r.compliance_status == "breach" for r in assessment.results)
            and not any(
                f["run_id"] == assessment.assessment_run_id for f in manager.repository.flags(bid)
            )
            and not any(
                s["run_id"] == assessment.assessment_run_id and s["payload"]["triage"]
                for s in manager.repository.submissions(bid)
            )
        )
        if not (submission or flags or requests or untriaged):
            continue
        severity = max(
            [f["payload"]["severity"] for f in flags] + (["Critical"] if untriaged else []),
            key=lambda s: {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}[s],
            default="Critical" if untriaged else "Not flagged",
        )
        state = manager.state(submission) if submission else "Analyst submission pending"
        due = min(
            (r["payload"]["due"] for r in requests if r["payload"].get("due")), default="9999-12-31"
        )
        reason = "; ".join(f["payload"]["explanation"] for f in flags)
        if untriaged:
            reason = "Untriaged covenant breach. " + reason
        if requests:
            reason += f" · {len(requests)} outstanding request(s)"
        cases.append(
            dict(
                borrower_id=bid,
                name=borrower["borrower_name"],
                submission=submission,
                assessment=assessment,
                flags=flags,
                requests=requests,
                severity=severity,
                state=state,
                due=due,
                reason=reason or state,
                attention=bool(flags or requests or untriaged or state != "Reviewed"),
            )
        )
    return sorted(
        cases,
        key=lambda c: (
            {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(c["severity"], 4),
            c["due"],
            c["name"].casefold(),
        ),
    )
