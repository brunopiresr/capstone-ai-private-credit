"""Derive public references from executed domain results, never model-authored citations."""

from credit_monitoring.domain.agent import SourceReference
from credit_monitoring.domain.assessment import RiskAssessment
from credit_monitoring.domain.documents import RetrievedRecord
from credit_monitoring.domain.processing import DocumentExtraction
from credit_monitoring.domain.tool_results import ToolOutcome


def result_sources(outcome: ToolOutcome) -> list[SourceReference]:
    references = []
    if isinstance(outcome, DocumentExtraction) and outcome.status == "complete":
        references.append(
            SourceReference(document_id=outcome.document_id, citation=outcome.citation)
        )
    elif isinstance(outcome, RiskAssessment):
        for result in outcome.results + outcome.history:
            for evidence in result.evidence:
                if evidence.get("document_id") and evidence.get("citation"):
                    references.append(
                        SourceReference(
                            document_id=evidence["document_id"], citation=evidence["citation"]
                        )
                    )
    elif isinstance(outcome, list):
        references.extend(
            SourceReference(document_id=record.document_id, citation=record.citation)
            for record in outcome
            if isinstance(record, RetrievedRecord)
        )
    return list({(source.document_id, source.citation): source for source in references}.values())
