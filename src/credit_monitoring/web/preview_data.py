"""Self-contained sample state for the UX preview. No repositories or service calls."""

from copy import deepcopy
from datetime import UTC, datetime


def timestamp() -> str:
    return datetime.now(UTC).strftime("%d %b %Y · %H:%M UTC")


def initial_preview() -> dict:
    """Return fresh, session-local fixtures; these are illustrative UI values only."""
    rows = [
        ("SYN001", "Harbor Components", "Industrials", "Compliant", 3.12, 5.50, 3.4, 3.7),
        ("SYN002", "Northstar Packaging", "Packaging", "Compliant", 4.85, 5.00, 1.8, 4.1),
        ("SYN003", "Elmwood Services", "Business services", "Breach", 5.20, 4.50, 1.6, 4.7),
        ("SYN004", "Cedar Logistics", "Logistics", "Compliant", 5.40, 5.50, 2.1, 5.2),
        ("SYN005", "Summit Retail", "Retail", "Waived", 5.20, 4.50, 1.4, 5.0),
        ("SYN006", "Beacon Software", "Software", "Compliant", 3.80, 4.50, 2.9, 3.6),
        ("SYN007", "Riverside Foods", "Food manufacturing", "Incomplete", None, 4.25, None, 4.0),
        ("SYN008", "Atlas Manufacturing", "Manufacturing", "Breach", 4.90, 4.50, 1.2, 4.3),
        ("SYN009", "Juniper Healthcare", "Healthcare", "Breach", 4.70, 4.50, 1.3, 4.2),
        ("SYN010", "Orion Distribution", "Distribution", "Not tested", None, 4.50, 2.2, None),
        ("SYN011", "Meadow Telecom", "Telecom", "Compliant", 3.60, 4.00, 2.6, 3.4),
        ("SYN012", "Pioneer Security", "Security services", "Not assessed", None, None, None, None),
    ]
    summaries = {
        "SYN001": "Stable earnings and comfortable leverage headroom support routine monitoring.",
        "SYN002": "Leverage is close to its limit after two quarters of earnings pressure.",
        "SYN003": "Leverage exceeds the covenant limit. A remediation plan needs review.",
        "SYN004": "Limited headroom under the amended agreement warrants closer monitoring.",
        "SYN005": "The leverage test is waived for this period. Keep the expiry date in view.",
        "SYN006": "Leverage remains within the limit after applying the contractual addback cap.",
        "SYN007": (
            "Financial statements and the compliance certificate report different debt figures."
        ),
        "SYN008": "Leverage exceeds the limit while interest coverage continues to weaken.",
        "SYN009": "Deteriorating operating performance has pushed leverage above its limit.",
        "SYN010": "The springing test is inactive for this reporting period.",
        "SYN011": "Net leverage remains within the limit after the cash-netting cap.",
        "SYN012": "Documents have been registered. An initial assessment is still needed.",
    }
    borrowers = {}
    for borrower_id, name, sector, status, leverage, limit, coverage, previous in rows:
        borrowers[borrower_id] = {
            "id": borrower_id,
            "name": name,
            "sector": sector,
            "status": status,
            "leverage": leverage,
            "limit": limit,
            "coverage": coverage,
            "previous": previous,
            "period": "Q3 2026",
            "period_end": "30 Sep 2026",
            "summary": summaries[borrower_id],
            "analyst": "Alex Morgan",
            "version": 0 if status == "Not assessed" else 1,
            "review_version": 0 if status == "Not assessed" else 1,
            "validated": borrower_id in {"SYN002", "SYN003", "SYN007", "SYN008"},
            "submitted": borrower_id in {"SYN002", "SYN003", "SYN007", "SYN008"},
            "validation_note": "Debt requires reconciliation; submitted with exceptions."
            if borrower_id == "SYN007"
            else "",
            "analyst_report": summaries[borrower_id],
            "manager_note": "",
            "recommendation": "Pending manager review",
            "contexts": [],
            "history": [],
            "needs_review": False,
        }
    flag_specs = [
        (
            "SYN002",
            "High",
            "Deterioration",
            "Headroom narrowed to 0.15x; review downside resilience.",
            "Request monthly reporting and a liquidity update.",
        ),
        (
            "SYN003",
            "Critical",
            "Covenant breach",
            "Leverage of 5.20x exceeds the 4.50x limit.",
            "Obtain a remediation plan and review amendment options.",
        ),
        (
            "SYN007",
            "High",
            "Data quality",
            "Debt figures conflict across two reporting sources.",
            "Reconcile debt before accepting the compliance assessment.",
        ),
        (
            "SYN008",
            "Critical",
            "Covenant breach",
            "Leverage exceeds the limit; coverage has weakened.",
            "Escalate and request a 13-week liquidity forecast.",
        ),
    ]
    flags = [
        {
            "id": f"FLAG-{i:03}",
            "borrower_id": bid,
            "severity": severity,
            "category": category,
            "explanation": explanation,
            "action": action,
            "status": "Pending review",
            "created": "28 Oct 2026",
            "version": 1,
        }
        for i, (bid, severity, category, explanation, action) in enumerate(flag_specs, 1)
    ]
    documents = []
    for bid in borrowers:
        for suffix, title, kind, status in (
            ("FIN", "Quarterly financial statements", "Financial statements", "Processed"),
            ("AGR", "Credit agreement & amendments", "Credit agreement", "Processed"),
            ("CERT", "Compliance certificate", "Compliance certificate", "Not fetched"),
        ):
            if bid == "SYN012":
                status = "Not fetched"
            if bid == "SYN007" and suffix == "FIN":
                status = "Needs review"
            documents.append(
                {
                    "id": f"{bid}-{suffix}",
                    "borrower_id": bid,
                    "title": title,
                    "type": kind,
                    "date": "30 Sep 2026",
                    "status": status,
                    "url": f"https://example.com/preview/{bid.lower()}/{suffix.lower()}",
                }
            )
    return {
        "borrowers": borrowers,
        "flags": flags,
        "documents": documents,
        "requests": [],
        "comments": [],
        "reports": [],
        "operations": [],
        "events": [],
        "chats": {},
        "board_draft": {},
    }


def active_flags(data: dict, borrower_id: str | None = None) -> list[dict]:
    return [
        flag
        for flag in data["flags"]
        if flag["status"] != "Resolved"
        and (borrower_id is None or flag["borrower_id"] == borrower_id)
    ]


def log_event(data: dict, borrower_id: str, title: str, detail: str = "") -> None:
    data["events"].insert(
        0,
        {
            "borrower_id": borrower_id,
            "title": title,
            "detail": detail,
            "at": timestamp(),
        },
    )


def simulate_assessment(data: dict, borrower_id: str, reason: str) -> None:
    borrower = data["borrowers"][borrower_id]
    borrower["history"].insert(
        0,
        {
            "version": borrower["version"],
            "status": borrower["status"],
            "summary": borrower["summary"],
            "report": borrower["analyst_report"],
        },
    )
    borrower["version"] += 1
    borrower["validated"] = False
    borrower["submitted"] = False
    borrower["needs_review"] = False
    # A UI preview cannot turn an unassessed borrower into a calculated result.
    log_event(data, borrower_id, f"Sample assessment v{borrower['version']} created", reason)


def simulate_review(data: dict, borrower_id: str, context: str = "") -> None:
    borrower = data["borrowers"][borrower_id]
    borrower["review_version"] += 1
    borrower["contexts"].insert(
        0,
        {
            "version": borrower["review_version"],
            "context": context,
            "at": timestamp(),
        },
    )
    log_event(data, borrower_id, f"Sample credit review v{borrower['review_version']}", context)


def add_flag(
    data: dict, borrower_id: str, severity: str, category: str, explanation: str, action: str
) -> dict:
    flag = {
        "id": f"FLAG-{len(data['flags']) + 1:03}",
        "borrower_id": borrower_id,
        "severity": severity,
        "category": category,
        "explanation": explanation,
        "action": action,
        "status": "Pending review"
        if data["borrowers"][borrower_id]["submitted"]
        else "Analyst draft",
        "created": timestamp(),
        "version": data["borrowers"][borrower_id]["version"],
    }
    data["flags"].append(flag)
    log_event(data, borrower_id, "Borrower flagged", explanation)
    return flag


def request_analysis(
    data: dict, borrower_id: str, question: str, context: str, owner: str, due: str
) -> dict:
    borrower = data["borrowers"][borrower_id]
    request = {
        "id": f"REQ-{len(data['requests']) + 1:03}",
        "borrower_id": borrower_id,
        "question": question,
        "context": context,
        "owner": owner,
        "due": due,
        "status": "Open",
        "version": borrower["version"],
        "review_version": borrower["review_version"],
        "response": "",
        "created": timestamp(),
    }
    data["requests"].append(request)
    for flag in active_flags(data, borrower_id):
        flag["status"] = "Changes requested"
    log_event(data, borrower_id, "Further analysis requested", question)
    return request


def complete_request(data: dict, request_id: str, response: str) -> None:
    request = next(item for item in data["requests"] if item["id"] == request_id)
    borrower = data["borrowers"][request["borrower_id"]]
    request.update(
        {
            "status": "Response ready",
            "response": response,
            "response_version": borrower["version"],
            "response_review_version": borrower["review_version"],
        }
    )
    for flag in active_flags(data, borrower["id"]):
        flag["status"] = "Pending review"
    log_event(data, borrower["id"], "Analyst response submitted", response)


def sample_reply(data: dict, borrower_id: str, question: str) -> str:
    borrower = data["borrowers"][borrower_id]
    lower = question.casefold()
    if any(word in lower for word in ("recalcul", "rerun", "re-run")):
        return (
            "Use **Recalculate** above the analysis to try the versioning flow. "
            "This preview keeps the sample figures unchanged."
        )
    if any(word in lower for word in ("draft", "note", "report")):
        return (
            f"**Suggested observation for {borrower['name']}**\n\n{borrower['summary']} "
            "Confirm the source information, document any exceptions, and agree the next "
            "monitoring action before completing review.\n\n"
            "You can edit and save this in **Analyst handoff**."
        )
    if any(word in lower for word in ("chang", "trend", "quarter")):
        previous, current = borrower["previous"], borrower["leverage"]
        if previous is not None and current is not None:
            return (
                f"The sample leverage moves from **{previous:.2f}x to {current:.2f}x**. "
                "Check earnings, debt movements and any definition changes in the "
                "**Calculations** tab before interpreting that change."
            )
    return (
        f"**{borrower['name']} · {borrower['period']}**\n\n{borrower['summary']}\n\n"
        "The sample assessment is **" + borrower["status"].lower() + "**. "
        "Review the covenant inputs and source references in **Calculations**. "
        "The bull and bear cases illustrate the two perspectives in **Credit analysis**."
    )


def sample_credit_snapshot(borrower: dict) -> dict:
    """Illustrative arguments shared by both views, without invoking any agents."""
    status = borrower["status"]
    leverage, limit = borrower["leverage"], borrower["limit"]
    if status == "Not assessed":
        return {}
    if status == "Breach":
        bull_thesis = "A recovery path is still possible"
        bull_argument = "A supported earnings recovery could help restore covenant compliance."
        bear_argument = f"Leverage of {leverage:.2f}x exceeds the {limit:.2f}x covenant limit."
        action = "Escalate for remediation"
        reasoning = [
            "The sample breach requires an explicit remediation plan.",
            "The bull case depends on recovery assumptions that still need evidence.",
            "Obtain near-term liquidity reporting and agree an owner and deadline.",
        ]
    elif status == "Incomplete":
        bull_thesis = "Reconciliation could clarify the position"
        bull_argument = "Resolving the debt discrepancy may establish a usable compliance basis."
        bear_argument = "Conflicting debt figures prevent a supported compliance conclusion."
        action = "Defer the compliance conclusion"
        reasoning = [
            "Source conflicts outweigh the conditional mitigants in the bull case.",
            "Reconcile debt and obtain a corrected compliance certificate.",
            "Recalculate and validate before relying on the compliance outcome.",
        ]
    elif status in {"Waived", "Not tested"}:
        bull_thesis = "The current test is not active"
        bull_argument = "The sample waiver or springing terms explain the inactive test."
        bear_argument = "An inactive test does not establish that the borrower is compliant."
        action = "Monitor test applicability"
        reasoning = [
            "Keep the inactive test separate from an affirmative compliance result.",
            "Verify the waiver expiry or springing trigger against the agreement.",
            "Continue monitoring earnings and liquidity before the next test.",
        ]
    else:
        bull_thesis = "Current leverage remains within the limit"
        bull_argument = f"Leverage of {leverage:.2f}x is below the {limit:.2f}x limit."
        bear_argument = f"Only {limit - leverage:.2f}x of leverage headroom absorbs a setback."
        narrow = limit - leverage < 0.5
        action = "Increase monitoring" if narrow else "Maintain routine monitoring"
        reasoning = [
            "Current compliance supports continued monitoring of the existing exposure.",
            "Limited headroom warrants a closer reporting cadence."
            if narrow
            else "The downside arguments require periodic earnings and cash checks.",
            "Confirm liquidity and recovery assumptions before changing the risk view.",
        ]
    previous = borrower["previous"]
    performance = (
        f"Leverage moved from {previous:.2f}x to {leverage:.2f}x since the prior quarter."
        if previous is not None and leverage is not None
        else "Incomplete or inactive results limit a reliable quarter-on-quarter comparison."
    )
    return {
        "bullish": {
            "name": "Bullish agent",
            "label": "Bull case",
            "tone": "green",
            "thesis": bull_thesis,
            "arguments": [
                bull_argument,
                "Cost control and improved cash collection could support stabilization.",
                "Timely reporting and a credible plan could strengthen confidence.",
            ],
            "basis": "Sample basis: financial statements and management assumptions.",
        },
        "bearish": {
            "name": "Bearish agent",
            "label": "Bear case",
            "tone": "amber",
            "thesis": "Downside resilience needs scrutiny",
            "arguments": [
                bear_argument,
                performance,
                "An earnings decline or unexpected cash outflow could increase pressure.",
            ],
            "basis": "Sample basis: covenant schedule, trends and source limitations.",
        },
        "recommendation": {
            "name": "Recommendation agent",
            "label": "Synthesis",
            "tone": "green",
            "thesis": action,
            "arguments": reasoning,
            "basis": "Advisory synthesis of the bull and bear arguments; manager decides.",
        },
    }


def board_items(data: dict) -> list[dict]:
    """Resolve a complete list of active flagged borrowers, plus untriaged breaches."""
    flagged = {flag["borrower_id"] for flag in active_flags(data)}
    borrower_ids = flagged | {
        bid for bid, borrower in data["borrowers"].items() if borrower["status"] == "Breach"
    }
    items = []
    for bid in sorted(borrower_ids):
        borrower = data["borrowers"][bid]
        flags = active_flags(data, bid)
        prior_flags = [flag for flag in data["flags"] if flag["borrower_id"] == bid]
        report_flags = flags or prior_flags
        items.append(
            {
                "borrower_id": bid,
                "name": borrower["name"],
                "sector": borrower["sector"],
                "status": borrower["status"],
                "period": borrower["period"],
                "explanation": " ".join(flag["explanation"] for flag in report_flags)
                if report_flags
                else "Calculated breach awaiting analyst triage.",
                "risk": borrower["summary"],
                "recommendation": borrower["recommendation"],
                "analyst_report": borrower["analyst_report"],
                "manager_note": borrower["manager_note"],
                "version": borrower["version"],
                "review_version": borrower["review_version"],
                "review_state": flags[0]["status"]
                if flags
                else ("Flag resolved · Breach remains" if prior_flags else "Untriaged breach"),
                "severity": "Critical"
                if any(flag["severity"] == "Critical" for flag in flags)
                or borrower["status"] == "Breach"
                else "High",
                "requests": [
                    deepcopy(item)
                    for item in data["requests"]
                    if item["borrower_id"] == bid and item["status"] != "Accepted"
                ],
            }
        )
    return items


def finalize_report(data: dict, title: str, period: str, summary: str, items: list[dict]) -> dict:
    """Freeze the sample report independently of future edits to preview state."""
    report = deepcopy(
        {
            "id": f"BOARD-{len(data['reports']) + 1:03}",
            "title": title,
            "period": period,
            "summary": summary,
            "items": items,
            "created": timestamp(),
            "borrowers": len(data["borrowers"]),
            "breaches": sum(b["status"] == "Breach" for b in data["borrowers"].values()),
            "flagged": len({flag["borrower_id"] for flag in active_flags(data)}),
        }
    )
    data["reports"].append(report)
    return report
