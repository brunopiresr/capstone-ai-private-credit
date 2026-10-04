"""SEC covenant extraction V2: structured facts, without legal or financial assessments."""

from datetime import date
from typing import Literal

from pydantic import Field

from .base import ExtractionModel
from .evidence import SourceEvidence
from .financials import FinancialMetricDefinition, ReportedFinancialValue


class ThresholdScheduleEntry(ExtractionModel):
    threshold: str = Field(
        description="Exact source threshold including precision, units, and ratios."
    )
    period_end_dates: list[date] = Field(
        default_factory=list,
        description="Individually named test period ends in ISO 8601 sharing this threshold; empty "
        "if unavailable. Never generate intermediate dates.",
    )
    from_period_end: date | None = Field(
        default=None,
        description="Explicit inclusive test period range start or start of 'and thereafter', "
        "in ISO 8601; null if unavailable.",
    )
    through_period_end: date | None = Field(
        default=None,
        description="Explicit inclusive test period range end in ISO 8601; null if unavailable "
        "or the clause is open-ended.",
    )
    measurement_basis: str | None = Field(
        default=None,
        description="Source-stated measurement basis; null if unavailable; do not infer.",
    )
    evidence: SourceEvidence = Field(
        description="Single excerpt supporting both threshold and applicability dates; split or "
        "flag unresolved combinations when facts come from different records."
    )


class CovenantTerm(ExtractionModel):
    covenant_name: str = Field(
        description="Exact name or source-supported short covenant description."
    )
    covenant_type: Literal[
        "leverage",
        "interest_coverage",
        "fixed_charge_coverage",
        "minimum_ebitda",
        "minimum_liquidity",
        "other",
    ] = Field(description="Classification of an explicitly identified covenant only.")
    metric: str | None = Field(
        default=None, description="Actual tested financial metric where named; null if unavailable."
    )
    threshold_schedule: list[ThresholdScheduleEntry] = Field(
        default_factory=list,
        description="All thresholds for this source-supported version, even one entry; empty if "
        "unavailable with a relevant gap. Do not merge successive amended versions.",
    )
    operator: Literal["<", "<=", ">", ">=", "="] | None = Field(
        default=None,
        description="Explicit comparison; Maximum/Minimum imply <=/>= unless specific wording "
        "overrides. Null if unsupported; record ambiguity.",
    )
    operator_quote: str | None = Field(
        default=None,
        description="Short verbatim phrase supporting the operator; null if unavailable.",
    )
    threshold_direction: Literal["maximum", "minimum", "other", "not_stated"] = Field(
        default="not_stated",
        description=(
            "Consistent with operator: </<= maximum, >/>= minimum, = other, null not_stated."
        ),
    )
    metric_definition_name: str | None = Field(
        default=None,
        description="Exact extracted contractual definition name only when explicitly linked to "
        "this covenant by source evidence; null otherwise; never link by name similarity.",
    )
    testing_period_or_frequency: str | None = Field(
        default=None, description="Source-stated test period or frequency; null if unavailable."
    )
    effective_date_or_period: str | None = Field(
        default=None,
        description="Source-stated covenant applicability; null if unavailable. Never substitute "
        "execution or filing dates.",
    )
    conditions_or_scope: str | None = Field(
        default=None,
        description="Explicit testing conditions or borrower scope; null if unavailable.",
    )
    agreement_name: str | None = Field(
        default=None, description="Explicitly associated agreement name; null if unavailable."
    )
    amendment_reference: str | None = Field(
        default=None, description="Explicitly associated amendment identifier; null if unavailable."
    )
    evidence: SourceEvidence = Field(
        description="Direct evidence of this covenant's identity/existence; thresholds have "
        "their own evidence. Results and compliance belong in compliance disclosures.",
    )


class AgreementAmendment(ExtractionModel):
    agreement_name: str | None = Field(
        default=None, description="Underlying agreement title as stated; null if unavailable."
    )
    amendment_name: str | None = Field(
        default=None, description="Exact amendment title as stated; null if unavailable."
    )
    amendment_number: str | None = Field(
        default=None, description="Exact amendment ordinal or number; null if unavailable."
    )
    execution_date: date | None = Field(
        default=None, description="Explicit execution date in ISO 8601; null if unavailable."
    )
    stated_effective_date: date | None = Field(
        default=None,
        description="Explicit effectiveness date in ISO 8601; null if unavailable; never infer "
        "from execution or filing dates.",
    )
    parties: list[str] = Field(
        default_factory=list, description="Source-named legal parties; empty if unavailable."
    )
    referenced_documents: list[str] = Field(
        default_factory=list,
        description="Source-referenced agreements, amendments, or exhibits; empty if unavailable.",
    )
    evidence: SourceEvidence = Field(
        description="Excerpt supporting agreement/amendment identity and every populated date."
    )


class CovenantTestingEvent(ExtractionModel):
    covenant_name: str = Field(
        description="Source-supported affected covenant name or covenant group."
    )
    event_type: Literal[
        "suspension",
        "resumption",
        "waiver",
        "modification",
        "addition",
        "removal",
        "default",
    ] = Field(
        description="Explicitly supported event only; waiver/suspension is not removal/compliance."
    )
    period_end_dates: list[date] = Field(
        default_factory=list,
        description=(
            "Specifically named affected test period ends in ISO 8601; empty if unavailable."
        ),
    )
    from_period_end: date | None = Field(
        default=None,
        description="Explicit inclusive first affected test period end in ISO 8601; else null.",
    )
    through_period_end: date | None = Field(
        default=None,
        description="Explicit inclusive last affected test period end in ISO 8601; else null.",
    )
    effective_date: date | None = Field(
        default=None, description="Explicit event effective date in ISO 8601; null if unavailable."
    )
    conditions: str | None = Field(
        default=None, description="Explicit event limits or triggers; null if unavailable."
    )
    amendment_reference: str | None = Field(
        default=None, description="Explicitly associated amendment identifier; null if unavailable."
    )
    evidence: SourceEvidence = Field(
        description="Excerpt supporting the event and affected periods."
    )


class ComplianceDisclosure(ExtractionModel):
    covenant_name: str | None = Field(
        default=None,
        description="Identified covenant; null for agreement-wide or unnamed disclosure.",
    )
    status: Literal[
        "compliant",
        "non_compliant",
        "deemed_compliant",
        "waived_default",
        "other",
    ] = Field(
        description="Explicitly reported status only; do not infer from waiver or suspension."
    )
    reported_result: str | None = Field(
        default=None,
        description="Source-disclosed test ratio/amount/result, with units; null if absent.",
    )
    assessment_date: date | None = Field(
        default=None, description="Explicit date the disclosure applies to in ISO 8601; else null."
    )
    description: str = Field(
        description="Source-supported disclosure preserving scope and qualifications."
    )
    amendment_reference: str | None = Field(
        default=None, description="Explicit amendment association; null if unavailable."
    )
    evidence: SourceEvidence = Field(description="Excerpt supporting disclosed status and result.")


class CreditFacilityTerm(ExtractionModel):
    term_type: Literal[
        "commitment",
        "availability_block",
        "borrowing_base",
        "maturity",
        "interest_margin",
        "reporting_requirement",
        "distribution_restriction",
        "other",
    ] = Field(
        description=(
            "Classification of the source-reported facility term; commitment is not availability."
        )
    )
    value: str | None = Field(
        default=None,
        description="Exact source amount/rate/date/text with stated units; null if unavailable.",
    )
    from_date: date | None = Field(
        default=None,
        description="Explicit inclusive term applicability start in ISO 8601; else null.",
    )
    through_date: date | None = Field(
        default=None,
        description="Explicit inclusive term applicability end in ISO 8601; else null.",
    )
    conditions: str | None = Field(
        default=None, description="Explicit restrictions or triggers; null if unavailable."
    )
    amendment_reference: str | None = Field(
        default=None, description="Explicitly linked amendment identifier; null if unavailable."
    )
    evidence: SourceEvidence = Field(
        description="Excerpt supporting this facility term and stated dates."
    )


class CovenantExtraction(ExtractionModel):
    issuer: str | None = Field(
        default=None, description="Explicit SEC registrant/issuer; null if unavailable."
    )
    ticker: str | None = Field(
        default=None, description="Explicitly supplied ticker only; null if unavailable."
    )
    borrower: str | None = Field(
        default=None,
        description="Explicit borrowing legal entity; null if absent; do not assume issuer.",
    )
    guarantors: list[str] = Field(
        default_factory=list,
        description="Explicitly identified legal guarantors; empty if unavailable.",
    )
    agreements: list[AgreementAmendment] = Field(
        default_factory=list,
        description="Supported original agreements and amendments; empty if unavailable.",
    )
    covenants: list[CovenantTerm] = Field(
        default_factory=list,
        description="All supported covenant versions and schedules; empty if unavailable.",
    )
    financial_metric_definitions: list[FinancialMetricDefinition] = Field(
        default_factory=list,
        description="Contractual definitions and supported adjustments, even without a full "
        "definition "
        "or explicit covenant link; empty if unavailable.",
    )
    testing_events: list[CovenantTestingEvent] = Field(
        default_factory=list, description="Explicit testing/legal events; empty if unavailable."
    )
    reported_financial_values: list[ReportedFinancialValue] = Field(
        default_factory=list,
        description="Source-disclosed amounts/ratios only; empty if unavailable.",
    )
    compliance_disclosures: list[ComplianceDisclosure] = Field(
        default_factory=list,
        description="Explicit results/compliance assertions; empty if unavailable.",
    )
    credit_facility_terms: list[CreditFacilityTerm] = Field(
        default_factory=list, description="Explicit facility terms; empty if unavailable."
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Relevant unavailable information in supplied excerpts, not claims about whole "
        "filings; empty if none identified.",
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="Genuine contradictions with citations where possible; normal sequential "
        "amendments are not conflicts; empty if none identified.",
    )
    extraction_warnings: list[str] = Field(
        default_factory=list,
        description="Source typos, contradictory dates, ambiguity, truncation, provenance or "
        "verification issues; preserve uncorrected source text; empty if none identified.",
    )


class CompanyCovenantExtraction(ExtractionModel):
    company: str = Field(description="Exact supplied catalog company name for this batch entry.")
    ticker: str = Field(description="Exact supplied catalog ticker; one entry per ticker.")
    extraction: CovenantExtraction = Field(
        description="Complete V2 extraction for this company only."
    )


class AllCompanyCovenantExtraction(ExtractionModel):
    summary: str = Field(
        description="Evidence-backed batch summary; no calculations or legal conclusions."
    )
    companies: list[CompanyCovenantExtraction] = Field(
        default_factory=list,
        description="Exactly one entry per catalog ticker, including sparse evidence.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Batch-level missing information in supplied excerpts; empty if none.",
    )
    conflicts: list[str] = Field(
        default_factory=list, description="Genuine batch-level contradictions; empty if none."
    )
