"""Copy agent-selected source facts into public tables without retyping or inference."""

from typing import Literal

from pydantic import Field, StrictStr

from credit_monitoring.agents.evidence import EvidenceRegistry
from credit_monitoring.domain.agent import AnswerDraft, AnswerTable, AnswerTableRow, SourceReference
from credit_monitoring.domain.base import ExtractionModel
from credit_monitoring.domain.covenant import CovenantTerm
from credit_monitoring.domain.processing import DocumentExtraction


class SourceTableSelection(ExtractionModel):
    document_id: StrictStr = Field(
        min_length=1,
        description="Exact catalog document_id of a complete extraction already read in this chat.",
    )
    section: Literal["covenant_schedules", "reported_values"] = Field(
        description="Copy full covenant schedules or source-reported financial values."
    )
    names: list[StrictStr] = Field(
        default_factory=list,
        description=(
            "Exact covenant_name or metric_name values to include. An empty list selects all "
            "items in this section of this extraction; it never chooses a governing version."
        ),
    )


class SourceTableDraft(AnswerDraft):
    """Internal model output; selectors are consumed before returning the public answer."""

    tables: list[AnswerTable] = Field(
        default_factory=list,
        description=(
            "Custom or partial tables. Use source_tables for complete extracted schedules "
            "and reported-value tables so their rows and citations are copied exactly."
        ),
    )

    source_tables: list[SourceTableSelection] = Field(
        default_factory=list,
        description=(
            "For requested complete source schedules, select their complete extraction here "
            "instead of retyping rows in tables or findings. The application copies EVERY "
            "explicit quarter, threshold and exact citation. For requested reported actuals, "
            "select reported_values from the relevant filing extractions. Read those "
            "extractions first when necessary. Leave empty for explanations, clarifications, "
            "calculations and custom or partial tables."
        ),
    )


def source_table_documents(registry: EvidenceRegistry) -> dict[str, dict]:
    """Keep the latest observed extraction status for each filing."""
    return {
        entry.data["document_id"]: entry.data
        for entry in registry.entries
        if entry.kind == "filing" and "result" in entry.data
    }


def source_table_schema(registry: EvidenceRegistry) -> dict:
    """Only offer filing-table selections after a complete extraction has been read."""
    available = [
        document_id
        for document_id, data in source_table_documents(registry).items()
        if data.get("status") == "complete" and data.get("result") is not None
    ]
    if not available:
        return AnswerDraft.model_json_schema()
    schema = SourceTableDraft.model_json_schema()
    schema["$defs"]["SourceTableSelection"]["properties"]["document_id"]["enum"] = available
    return schema


def _schedule_table(document: DocumentExtraction, covenant: CovenantTerm) -> AnswerTable:
    if not covenant.threshold_schedule:
        raise ValueError(
            f"No schedule entries for {covenant.covenant_name}; report this source gap."
        )
    columns = ["Fiscal quarter / stated range", "Threshold"]
    if covenant.operator:
        columns.append("Operator")
    if any(entry.measurement_basis is not None for entry in covenant.threshold_schedule):
        columns.append("Measurement basis")
    if covenant.conditions_or_scope is not None:
        columns.append("Conditions / scope")
    rows = []
    for entry in covenant.threshold_schedule:
        periods = [str(day) for day in entry.period_end_dates]
        if entry.from_period_end is not None or entry.through_period_end is not None:
            periods.append(
                f"From {entry.from_period_end or 'not stated'} "
                f"through {entry.through_period_end or 'end not stated'}"
            )
        for period in periods or ["Not stated"]:
            cells = [period, entry.threshold]
            if "Operator" in columns:
                cells.append(covenant.operator)
            if "Measurement basis" in columns:
                cells.append(entry.measurement_basis or "Not stated")
            if "Conditions / scope" in columns:
                cells.append(covenant.conditions_or_scope)
            rows.append(
                AnswerTableRow(
                    cells=cells,
                    citations=[
                        SourceReference(
                            document_id=entry.evidence.document_id, citation=entry.evidence.citation
                        )
                    ],
                )
            )
    version = f" ({covenant.amendment_reference})" if covenant.amendment_reference else ""
    return AnswerTable(
        title=f"{covenant.covenant_name}{version} — {document.document_id}",
        columns=columns,
        rows=rows,
    )


def _source_tables(
    document: DocumentExtraction, selection: SourceTableSelection
) -> list[AnswerTable]:
    extraction = document.result.extraction
    if selection.section == "covenant_schedules":
        items = extraction.covenants
        available = {item.covenant_name for item in items}
    else:
        items = extraction.reported_financial_values
        available = {item.metric_name for item in items}
    if missing := set(selection.names) - available:
        raise ValueError(
            f"Source item names not found: {sorted(missing)}. Available: {sorted(available)}"
        )
    if not items:
        raise ValueError(f"No {selection.section} in this extraction; report its evidence gap.")
    if selection.section == "covenant_schedules":
        return [
            _schedule_table(document, item)
            for item in items
            if not selection.names or item.covenant_name in selection.names
        ]
    rows = [
        AnswerTableRow(
            cells=[
                item.metric_name,
                str(item.period_end) if item.period_end else "Not stated",
                item.reported_value,
                item.measurement_period or "Not stated",
                item.accounting_basis or "Not stated",
            ],
            citations=[
                SourceReference(
                    document_id=item.evidence.document_id, citation=item.evidence.citation
                )
            ],
        )
        for item in items
        if not selection.names or item.metric_name in selection.names
    ]
    return [
        AnswerTable(
            title=f"Source-reported values — {document.document_id}",
            columns=[
                "Metric",
                "Period end",
                "Reported value",
                "Measurement period",
                "Accounting basis",
            ],
            rows=rows,
        )
    ]


def materialize_source_tables(
    draft: AnswerDraft, registry: EvidenceRegistry, *, partial: bool = False
) -> AnswerDraft:
    """Only copy explicitly selected, available source data; never inspect question wording."""
    if not isinstance(draft, SourceTableDraft):
        return draft
    answer = AnswerDraft.model_validate(draft.model_dump(exclude={"source_tables"}))
    documents = source_table_documents(registry)
    copied = set()
    for selection in draft.source_tables:
        try:
            data = documents.get(selection.document_id)
            if data is None:
                raise ValueError(
                    f"{selection.document_id} is not a loaded complete filing extraction. "
                    "Remove this source_tables selection. Present assessment results, "
                    "calculations and CSV financials in findings or custom tables; their IDs "
                    "are not catalog document IDs. Report unavailable filing tables as a gap."
                )
            if data.get("status") != "complete" or data.get("result") is None:
                raise ValueError(
                    "Source tables require a complete extraction, not metadata or passages."
                )
            document = DocumentExtraction.model_validate(data)
            tables = _source_tables(document, selection)
        except ValueError:
            if partial:
                continue
            raise
        for table in tables:
            key = table.model_dump_json()
            if key not in copied:
                answer.tables.append(table)
                copied.add(key)
    return answer
