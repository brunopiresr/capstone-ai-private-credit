"""Validate claim links and render one cited answer for every consumer.

Reference membership and copied facts are deterministic. Narrative entailment is
explicitly a separate semantic grading dimension, never inferred from a real ID.
"""

import json
import re
from collections import defaultdict

from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.agents.request_policy import RequestContext
from credit_monitoring.domain.agent import AnswerContent, MaterialClaim

SCHEMA_VERSION = "agent-answer-v2"


def select(data: dict, path: str):
    value = data
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError(f"Evidence does not contain field {path}.")
    return value


def validate_claim(
    claim: MaterialClaim, registry: EvidenceRegistry, context: RequestContext
) -> None:
    if not claim.claim_id.strip() or not claim.evidence_ids:
        raise ValueError("Every material claim needs an ID and actual evidence references.")
    entries = [registry.get(key) for key in claim.evidence_ids]
    notes = " ".join([*claim.assumptions, *claim.limitations])
    if re.search(r"\d|\b(?:compliant|in breach|waived|guaranteed|no credit risk)\b", notes, re.I):
        raise ValueError("Notes cannot introduce uncited numbers or statuses.")
    for entry in entries:
        for name in ("borrower_id", "ticker", "period_end", "information_cutoff"):
            supplied = getattr(claim, name)
            if supplied is not None and supplied != getattr(entry, name):
                raise ValueError(f"Claim {claim.claim_id}: {name} does not match its evidence.")
        if entry.borrower_id and entry.borrower_id != context.borrower_id:
            raise ValueError("Claim evidence is outside this borrower scope.")
        if entry.ticker and context.ticker and entry.ticker != context.ticker:
            raise ValueError("Claim evidence is outside this issuer scope.")
        if (
            context.reporting
            and entry.borrower_id
            and entry.period_end
            and (entry.period_end > str(context.reporting.value))
        ):
            raise ValueError("Claim uses financial evidence later than the reporting date.")
        if (
            context.cutoff
            and entry.information_cutoff
            and (entry.information_cutoff > str(context.cutoff.value))
        ):
            raise ValueError("Claim evidence was obtained under a later information cutoff.")
    if claim.kind == "fact":
        if len(entries) != 1 or not claim.field_path:
            raise ValueError("A fact must select one field from one evidence entry.")
        value = select(entries[0].data, claim.field_path)
        if claim.value_json is not None:
            copied = json.loads(claim.value_json)
            if copied != value or (isinstance(copied, bool) != isinstance(value, bool)):
                raise ValueError(
                    "Copied fact differs from the authoritative field (including nulls)."
                )
        if claim.unit is not None and claim.unit != entries[0].data.get("unit"):
            raise ValueError("Claim unit differs from the authoritative result.")
        if claim.statement.strip():
            raise ValueError(
                "Fact labels/values are rendered by the application; leave statement empty."
            )
    elif claim.kind == "quote":
        if not claim.statement.strip() or not any(
            claim.statement in entry.data.get("text", "") for entry in entries
        ):
            raise ValueError("Quoted filing claims must occur verbatim in the referenced passage.")
    else:
        if not claim.statement.strip():
            raise ValueError("Narrative claims require a statement.")
        # Numerical and status assertions belong in field selectors, not recreated prose.
        text = claim.statement
        for entry in entries:
            for value in (entry.borrower_id, entry.ticker, entry.period_end):
                if value:
                    text = text.replace(value, "")
        if re.search(r"\d|\b(?:compliant|in breach|not_tested|waived)\b", text, re.I):
            raise ValueError("Use fact selectors or exact passage quotes for numbers and statuses.")
        if re.search(
            r"\b(?:sound credit management|guaranteed|no (?:credit )?risk|"
            r"clean compliance|financially sound|safe investment)\b",
            text,
            re.I,
        ):
            raise ValueError("The evidence does not establish categorical credit reassurance.")


def core_claims(registry: EvidenceRegistry, assessment_ids: set[str]) -> list[MaterialClaim]:
    claims = []
    for entry in registry.entries:
        if entry.kind == "assessment" and entry.data["assessment_run_id"] in assessment_ids:
            for path in ("borrower_id", "period_end", "information_cutoff", "issues"):
                claims.append(
                    MaterialClaim(
                        claim_id=f"summary:{entry.evidence_id}:{path}",
                        kind="fact",
                        evidence_ids=[entry.evidence_id],
                        field_path=path,
                    )
                )
        if entry.kind != "calculation" or entry.data["assessment_run_id"] not in assessment_ids:
            continue
        for path in (
            "actual_value",
            "threshold",
            "operator",
            "unit",
            "headroom",
            "compliance_status",
            "financial_inputs.result_basis",
        ):
            if path == "financial_inputs.result_basis" and "result_basis" not in (
                entry.data.get("financial_inputs", {})
            ):
                continue
            claims.append(
                MaterialClaim(
                    claim_id=f"core:{entry.evidence_id}:{path}",
                    kind="fact",
                    evidence_ids=[entry.evidence_id],
                    field_path=path,
                )
            )
    return claims


def _display(value) -> str:
    if value is None:
        return "null (unavailable)"
    if isinstance(value, float):
        return f"{value:.8g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_claim(claim: MaterialClaim, registry: EvidenceRegistry) -> str:
    entries = [registry.get(key) for key in claim.evidence_ids]
    if claim.kind == "fact":
        value = select(entries[0].data, claim.field_path)
        subject = ", ".join(
            filter(None, (entries[0].borrower_id or entries[0].ticker, entries[0].period_end))
        )
        statement = (subject + " — " if subject else "") + (
            claim.field_path.replace("_", " ") + ": " + _display(value)
        )
    elif claim.kind == "quote":
        statement = f"“{claim.statement}”"
    else:
        statement = claim.statement
    if claim.assumptions:
        statement += " Assumptions: " + "; ".join(claim.assumptions)
    if claim.limitations:
        statement += " Limitations: " + "; ".join(claim.limitations)
    return statement + " [" + "; ".join(entry.citation for entry in entries) + "]"


def finalize_content(
    content: AnswerContent,
    registry: EvidenceRegistry,
    context: RequestContext,
    assessment_ids: set[str],
) -> AnswerContent:
    if content.confidence is None or not content.confidence_explanation.strip():
        raise ValueError("Provide confidence and its evidence explanation.")
    if content.schema_version != SCHEMA_VERSION:
        raise ValueError("Use schema_version agent-answer-v2 for newly generated answers.")
    if any(c.claim_id.startswith(("core:", "summary:", "policy:")) for c in content.claims):
        raise ValueError("Claim IDs cannot use application-owned prefixes.")
    claims = [*core_claims(registry, assessment_ids), *content.claims]
    identifiers = [claim.claim_id for claim in claims]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Claim IDs must be unique.")
    for claim in claims:
        validate_claim(claim, registry, context)
    if not content.claims:
        if any(entry.kind == "filing" for entry in registry.entries) and not claims:
            raise ValueError(
                "A filing answer requires explicit claims linked to retrieved passages."
            )
        # Discovery/clarification prose contains no material factual assertions.
        text = content.answer
        for value in (context.borrower_id, context.ticker):
            if value:
                text = text.replace(value, "")
        if re.search(
            r"\d|\b(?:compliant|breach|waived|threshold|probability|"
            r"sound credit management|financially sound)\b",
            text,
            re.I,
        ):
            raise ValueError(
                "Put every material statement in supported claims, not free-form answer."
            )
    paragraphs = []
    grouped = defaultdict(list)
    for claim in claims:
        if claim.claim_id.startswith("core:"):
            grouped[claim.evidence_ids[0]].append(claim)
        else:
            paragraphs.append(render_claim(claim, registry))
    for evidence_id, facts in grouped.items():
        entry = registry.get(evidence_id)
        data = entry.data
        heading = f"{data['covenant_id']} — {entry.period_end}"
        if covenant := data.get("resolved_covenant"):
            heading = f"{covenant['covenant_name']} ({data['covenant_id']}) — {entry.period_end}"
        paragraphs.insert(
            0,
            heading
            + ": "
            + "; ".join(
                fact.field_path.replace("_", " ") + " " + _display(select(data, fact.field_path))
                for fact in facts
            )
            + f" [{entry.citation}]",
        )
    if not paragraphs:
        if not content.answer.strip():
            raise ValueError("Provide a nonblank answer or supported claims.")
        paragraphs.append(content.answer)
    kind = context.intent if context.intent != "clarification" else "clarification"
    return content.model_copy(
        update={"answer": "\n\n".join(paragraphs), "claims": claims, "answer_kind": kind}, deep=True
    )
