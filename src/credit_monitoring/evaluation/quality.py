"""Versioned measurement contract, independent of generation prompts.

Historical captures are immutable. Regrades bind to their exact file hash and never
create claim links which the original displayed answer did not contain.
"""

import hashlib
import json
import re

from pydantic import BaseModel, Field

EVALUATOR_VERSION = "agent-quality-v2"
RUBRIC_VERSION = "agent-semantic-v2"
DIMENSIONS = (
    "execution",
    "workflow",
    "financial",
    "citations",
    "disclosures",
    "semantic",
)


def answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode()).hexdigest()


def requirements(expected: str) -> dict[str, str]:
    return {
        f"requirement:{i}": text.strip()
        for i, text in enumerate(re.split(r"(?<=[.;])\s+(?=[A-Z])", expected), 1)
        if text.strip()
    }


class RequirementFinding(BaseModel):
    requirement_id: str
    verdict: str = Field(description="pass, fail, or insufficient_evidence")
    excerpt: str | None = Field(description="Verbatim final-answer excerpt, or null if absent.")
    reason: str = Field(min_length=1)


def validate_findings(findings: list[RequirementFinding], packet: dict) -> None:
    ids = [f.requirement_id for f in findings]
    if len(ids) != len(set(ids)) or set(ids) != set(packet["requirements"]):
        raise ValueError("Grade each requirement exactly once.")
    for finding in findings:
        if finding.verdict not in {"pass", "fail", "insufficient_evidence"}:
            raise ValueError("Invalid requirement verdict.")
        if finding.excerpt is not None and finding.excerpt not in packet["final_answer"]:
            raise ValueError("Quoted excerpts must occur verbatim in the final answer.")
        if finding.verdict == "pass" and not finding.excerpt:
            raise ValueError("Absent answer content cannot be credited from the evidence.")


def judge_packet(case, answer, *, max_bytes: int = 120_000) -> dict:
    """No service narratives or redundant histories; refuse instead of truncating."""
    evidence = []
    for call in answer.tool_trace:
        data = call.model_dump(mode="json")["outcome"]
        if isinstance(data, dict):
            data.pop("narrative", None)
        evidence.append({"tool": call.name, "arguments": call.arguments, "result": data})
    packet = {
        "final_answer": answer.answer,
        "question": case.question,
        "context": {
            "borrower_id": case.borrower_id,
            "ticker": case.ticker,
            "period_end": case.period_end,
            "information_cutoff": case.information_cutoff,
        },
        "requirements": requirements(case.expected_behavior),
        "authoritative_evidence": evidence,
    }
    if len(json.dumps(packet, ensure_ascii=False).encode()) > max_bytes:
        raise ValueError("Required evidence exceeds packet budget; insufficient evidence.")
    return packet


def dimension(name: str) -> str:
    if name in {"completed", "nonblank_answer"}:
        return "execution"
    if name.startswith(("claim_", "citation_", "source_citation", "assessment_citation")):
        return "citations"
    if name.startswith("disclosure:"):
        return "disclosures"
    if name.startswith(("result:", "unique_result:", "assessment:")):
        return "financial"
    return "workflow"


def dimension_scores(checks: list[dict], grade: dict) -> dict:
    scores = {}
    for key in DIMENSIONS:
        applicable = [c for c in checks if dimension(c["name"]) == key]
        if key == "semantic":
            label = grade.get("label")
            scores[key] = {
                "passed": int(label == "pass"),
                "denominator": 1,
                "missing": int(label not in {"pass", "fail"}),
            }
        else:
            scores[key] = {
                "passed": sum(c["passed"] for c in applicable),
                "denominator": len(applicable),
                "missing": 0,
            }
    return scores


def historical_claim_link(text: str, identifiers: list[str], facts: list[str]) -> bool:
    """An unrelated endnote/run ID is insufficient; require an adjacent displayed fact."""
    return any(
        all(identifier in paragraph for identifier in identifiers)
        and any(
            re.search(r"(?<![\w.])" + re.escape(fact) + r"(?![\w.])", paragraph)
            for fact in facts
            if fact
        )
        for paragraph in re.split(r"\n\s*\n", text)
    )
