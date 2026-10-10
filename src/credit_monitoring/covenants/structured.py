"""Typed readers for existing synthetic terms and stored document extractions."""

import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from credit_monitoring.application.document_processing_service import DocumentProcessingService
from credit_monitoring.domain.analytics_base import AssessmentModel, CalculationFormula
from credit_monitoring.domain.assessment import (
    CovenantResolution,
    FinancialPeriod,
    ResolvedCovenant,
)
from credit_monitoring.observability.assessment import (
    covenant_terms,
    resolution_context,
    resolution_inputs,
    resolution_output,
    resolution_outputs,
)
from credit_monitoring.observability.logging import log_event, logged_operation, logging_context

from .applicability import applies_to_period, parse_ratio

logger = logging.getLogger(__name__)


class CovenantReader(Protocol):
    """Resolve stored terms for an explicitly identified borrower and reporting period."""

    def resolve(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        financials: FinancialPeriod,
    ) -> list[CovenantResolution]:
        """Select source-supported terms or return explicit resolution issues."""
        ...


class CalculationRules(AssessmentModel):
    """Explicitly configured calculation rules, never inferred from covenant name similarity."""

    formula: CalculationFormula
    measurement_basis: str
    cash_netting_cap: float | None = None
    addback_cap_fraction: float | None = None
    synergy_cap_fraction: float | None = None


_SYNTHETIC_FORMULAS = {
    "(total_debt - min(cash,20)) / adjusted_ebitda": ("net_leverage", 20),
    "(total_debt - min(cash,15)) / adjusted_ebitda": ("net_leverage", 15),
    "(total_debt - min(cash,25)) / adjusted_ebitda": ("net_leverage", 25),
    "total_debt / adjusted_ebitda": ("total_leverage", None),
    "total_debt / covenant_ebitda": ("total_leverage", None),
    "adjusted_ebitda / cash_interest": ("interest_coverage", None),
    "(adjusted_ebitda - capex - cash_taxes) / (cash_interest + scheduled_principal + rent)": (
        "fixed_charge_coverage",
        None,
    ),
    "fccr": ("fixed_charge_coverage", None),
    "total_debt / (reported_ebitda + acquired_ebitda + min(synergy_addback,0.5*acquired_ebitda))": (
        "pro_forma_leverage",
        None,
    ),
}


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SyntheticCovenantReader:
    """Read controlled covenant inputs without reading gold labels or financial notes."""

    def __init__(self, csv_path: str | Path) -> None:
        self.csv_path = Path(csv_path).resolve()
        with self.csv_path.open(newline="", encoding="utf-8-sig") as source:
            self.rows = list(enumerate(csv.DictReader(source), start=2))

    @logged_operation(
        inputs=resolution_inputs,
        outputs=resolution_outputs,
        context=resolution_context,
    )
    def resolve(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        financials: FinancialPeriod,
    ) -> list[CovenantResolution]:
        """Select explicit effective ranges and apply allowlisted synthetic rules."""
        grouped = {}
        for source_row, row in self.rows:
            if row["borrower_id"] == borrower_id:
                grouped.setdefault(row["covenant_id"], []).append((source_row, row))
        resolutions = []
        for source_id, versions in grouped.items():
            covenant_id = f"synthetic:{borrower_id}:{source_id}"
            active = []
            for line, row in versions:
                applies = date.fromisoformat(row["effective_start"]) <= period_end and (
                    not row["effective_end"]
                    or period_end <= date.fromisoformat(row["effective_end"])
                )
                log_event(
                    logger,
                    "synthetic_version",
                    covenant_id=covenant_id,
                    source_file=str(self.csv_path),
                    source_row=line,
                    inputs={
                        "effective_start": row["effective_start"],
                        "effective_end": row["effective_end"],
                    },
                    outputs={
                        "applicable": applies,
                        "reason": "Within effective range."
                        if applies
                        else "Outside effective range.",
                    },
                )
                if applies:
                    active.append((line, row))
            resolution = CovenantResolution(covenant_id=covenant_id, covenant_type=source_id)
            if len(active) != 1:
                resolution.issues.append("No unique covenant version applies to this period.")
                log_event(
                    logger,
                    "covenant_resolution",
                    covenant_id=covenant_id,
                    inputs={"candidate_count": len(active)},
                    outputs=resolution_output(resolution),
                )
                resolutions.append(resolution)
                continue
            line, row = active[0]
            evidence = [
                {
                    "source_file": str(self.csv_path),
                    "source_row": line,
                    "source_values": row,
                    "source_hash": _fingerprint(row),
                }
            ]
            resolution.evidence = evidence
            try:
                resolution.covenant = self._resolve_row(
                    row,
                    covenant_id,
                    period_end,
                    financials,
                    evidence,
                )
                resolution.covenant_type = resolution.covenant.covenant_type
            except ValueError as error:
                resolution.issues.append(str(error))
            log_event(
                logger,
                "covenant_resolution",
                covenant_id=covenant_id,
                source_file=str(self.csv_path),
                source_row=line,
                inputs={"candidate_count": len(active)},
                outputs=resolution_output(resolution),
            )
            resolutions.append(resolution)
        return resolutions

    def _resolve_row(
        self,
        row: dict,
        covenant_id: str,
        period_end: date,
        financials: FinancialPeriod,
        evidence: list[dict],
    ) -> ResolvedCovenant:
        formula_text = row["metric_formula"]
        if formula_text not in _SYNTHETIC_FORMULAS:
            raise ValueError("Unsupported synthetic calculation formula.")
        formula, cash_cap = _SYNTHETIC_FORMULAS[formula_text]
        expected_cash_rule = "none" if cash_cap is None else f"cash netting capped at {cash_cap}"
        if row["cash_netting_rule"] != expected_cash_rule:
            raise ValueError("Cash-netting rule conflicts with the allowlisted formula.")
        cap_fraction = None
        addback_rule = row["addback_rule"]
        if addback_rule == "eligible_addbacks capped at 20% of reported EBITDA":
            cap_fraction = 0.2
        elif addback_rule not in ("none", "synergy addback capped at 50% of acquired EBITDA"):
            raise ValueError("Unsupported synthetic addback rule.")
        testing_status = "active"
        condition = row["testing_condition"]
        if condition == "only if revolver_availability_pct < 25":
            availability = financials.metrics.get("revolver_availability_pct")
            if availability is None:
                testing_status = "unresolved"
            elif availability >= 25:
                testing_status = "inactive"
        elif condition != "quarterly":
            raise ValueError("Unsupported synthetic testing condition.")
        special_rule = row["waiver_or_special_rule"]
        if special_rule == "Testing waived for quarters ending 2025-06-30 and 2025-09-30":
            if period_end in (date(2025, 6, 30), date(2025, 9, 30)):
                testing_status = "waived"
        elif special_rule not in (
            "none",
            "Original agreement",
            "Amendment effective 2025-07-01 supersedes original threshold",
            "If material source conflict exists, do not issue compliance conclusion "
            "until reconciled",
            "No test when availability is 25% or higher",
            "Include acquired EBITDA on a pro forma basis",
        ):
            raise ValueError("Unsupported synthetic special rule.")
        log_event(
            logger,
            "synthetic_testing",
            covenant_id=covenant_id,
            inputs={
                "testing_condition": condition,
                "revolver_availability_pct": financials.metrics.get("revolver_availability_pct"),
                "waiver_or_special_rule": special_rule,
            },
            outputs={"testing_status": testing_status},
        )
        return ResolvedCovenant(
            borrower_id=row["borrower_id"],
            agreement_id=f"synthetic:{row['borrower_id']}",
            covenant_id=covenant_id,
            covenant_name=row["covenant_name"],
            covenant_type=formula,
            covenant_version=_fingerprint(row),
            period_end=period_end,
            threshold=float(row["threshold"]),
            operator=row["operator"],
            unit=row["unit"],
            formula=formula,
            measurement_basis="synthetic contractual inputs",
            cash_netting_cap=cash_cap,
            addback_cap_fraction=cap_fraction,
            synergy_cap_fraction=0.5 if formula == "pro_forma_leverage" else None,
            testing_status=testing_status,
            evidence=evidence,
        )


@dataclass(frozen=True)
class ExtractionBinding:
    """An explicit borrower/agreement/covenant mapping to one stored document."""

    borrower_id: str
    agreement_id: str
    covenant_id: str
    covenant_name: str
    document_id: str
    available_at: date | None = None
    calculation_rules: CalculationRules | None = None


class ExtractionCovenantReader:
    """Resolve existing V2 facts through explicit bindings without processing documents."""

    def __init__(
        self,
        service: DocumentProcessingService,
        bindings: list[ExtractionBinding],
    ) -> None:
        self.service = service
        self.bindings = bindings

    @logged_operation(
        inputs=resolution_inputs,
        outputs=resolution_outputs,
        context=resolution_context,
    )
    def resolve(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        financials: FinancialPeriod,
    ) -> list[CovenantResolution]:
        """Reject ambiguous terms; unavailable extractions remain unresolved."""
        grouped = {}
        for binding in self.bindings:
            if binding.borrower_id == borrower_id:
                grouped.setdefault(binding.covenant_id, []).append(binding)
        resolutions = []
        for covenant_id, bindings in grouped.items():
            with logging_context(covenant_id=covenant_id):
                resolution = CovenantResolution(covenant_id=covenant_id, covenant_type="unknown")
                candidates = []
                for binding in bindings:
                    with logging_context(
                        document_id=binding.document_id, agreement_id=binding.agreement_id
                    ):
                        if (
                            binding.available_at is not None
                            and binding.available_at > information_cutoff
                        ):
                            log_event(
                                logger,
                                "extraction_candidate",
                                status="rejected",
                                inputs={"available_at": binding.available_at},
                                outputs={"reason": "Source unavailable at information cutoff."},
                            )
                            continue
                        document = self.service.get_document_extraction(binding.document_id)
                        if document.status != "complete" or document.result is None:
                            resolution.issues.append(
                                f"Extraction unavailable: {binding.document_id}."
                            )
                            log_event(
                                logger,
                                "extraction_candidate",
                                status="rejected",
                                inputs={"extraction_status": document.status},
                                outputs={"reason": resolution.issues[-1]},
                            )
                            continue
                        if (
                            document.result.validation is not None
                            and not document.result.validation.is_valid
                        ):
                            resolution.issues.append(
                                f"Extraction has validation errors: {binding.document_id}."
                            )
                            log_event(
                                logger,
                                "extraction_candidate",
                                status="rejected",
                                outputs={"reason": resolution.issues[-1]},
                            )
                            continue
                        extraction = document.result.extraction
                        if extraction.conflicts:
                            resolution.issues.append(
                                f"Conflicting extracted facts: {binding.document_id}."
                            )
                            log_event(
                                logger,
                                "extraction_candidate",
                                status="rejected",
                                outputs={"reason": resolution.issues[-1]},
                            )
                            continue
                        for term in extraction.covenants:
                            if term.covenant_name != binding.covenant_name:
                                log_event(
                                    logger,
                                    "extraction_candidate",
                                    status="rejected",
                                    inputs={
                                        "covenant_name": term.covenant_name,
                                        "bound_covenant_name": binding.covenant_name,
                                    },
                                    outputs={"reason": "Covenant name does not match the binding."},
                                )
                                continue
                            resolution.covenant_type = term.covenant_type
                            for schedule in term.threshold_schedule:
                                if applies_to_period(schedule, period_end):
                                    try:
                                        candidate = self._candidate(
                                            binding,
                                            term,
                                            schedule,
                                            extraction,
                                            period_end,
                                            document,
                                        )
                                        candidates.append(candidate)
                                    except (ValueError, OSError) as error:
                                        resolution.issues.append(str(error))
                                        log_event(
                                            logger,
                                            "extraction_candidate",
                                            status="rejected",
                                            outputs={"reason": resolution.issues[-1]},
                                        )
                                else:
                                    log_event(
                                        logger,
                                        "extraction_candidate",
                                        status="rejected",
                                        inputs={"threshold": schedule.threshold},
                                        outputs={
                                            "reason": "Threshold schedule does not apply to period."
                                        },
                                    )
                if not resolution.issues and len(candidates) == 1:
                    resolution.covenant = candidates[0]
                    resolution.evidence = candidates[0].evidence
                else:
                    resolution.issues.append(
                        "No unique source-supported covenant applies to this period."
                    )
                log_event(
                    logger,
                    "covenant_resolution",
                    inputs={"candidate_count": len(candidates)},
                    outputs=resolution_output(resolution),
                )
                resolutions.append(resolution)
        return resolutions

    @logged_operation(
        inputs=lambda args: {
            "threshold": args["schedule"].threshold,
            "operator": args["term"].operator,
            "effective_date_or_period": args["term"].effective_date_or_period,
            "calculation_rules": args["binding"].calculation_rules.model_dump(mode="json")
            if args["binding"].calculation_rules
            else None,
        },
        outputs=lambda covenant: {"terms": covenant_terms(covenant)},
    )
    def _candidate(self, binding, term, schedule, extraction, period_end, document):
        """Check selected source quotes and project only explicit period-specific facts."""
        if term.operator is None:
            raise ValueError("Extracted covenant has no supported comparison operator.")
        if term.conditions_or_scope:
            raise ValueError("Extracted testing conditions require explicit structured resolution.")
        if term.effective_date_or_period:
            try:
                effective_date = date.fromisoformat(term.effective_date_or_period)
            except ValueError:
                raise ValueError(
                    "Covenant effective-period text requires explicit resolution."
                ) from None
            if effective_date > period_end:
                raise ValueError("Covenant is not effective for this reporting period.")
        covenant_names = {covenant.covenant_name for covenant in extraction.covenants}
        if any(event.covenant_name not in covenant_names for event in extraction.testing_events):
            raise ValueError("A testing event has an unresolved covenant-group scope.")
        for agreement in extraction.agreements:
            identifiers = (agreement.amendment_name, agreement.amendment_number)
            if term.amendment_reference and term.amendment_reference in identifiers:
                if agreement.stated_effective_date and agreement.stated_effective_date > period_end:
                    raise ValueError("Amendment is not effective for this reporting period.")
        applicable_events = [
            event
            for event in extraction.testing_events
            if (
                event.covenant_name == binding.covenant_name
                and applies_to_period(event, period_end)
            )
        ]
        unresolved_events = [
            event
            for event in extraction.testing_events
            if (
                event.covenant_name == binding.covenant_name
                and not event.period_end_dates
                and event.from_period_end is None
            )
        ]
        if unresolved_events or len(applicable_events) > 1:
            raise ValueError("Testing events require unambiguous period-specific applicability.")
        testing_status = "active"
        if applicable_events:
            event = applicable_events[0]
            if event.conditions or event.event_type not in ("waiver", "suspension", "resumption"):
                raise ValueError("Unsupported or conditional covenant testing event.")
            testing_status = {
                "waiver": "waived",
                "suspension": "suspended",
                "resumption": "active",
            }[event.event_type]
        log_event(
            logger,
            "extracted_testing",
            inputs={"applicable_event_types": [event.event_type for event in applicable_events]},
            outputs={"testing_status": testing_status},
        )
        actuals = [
            value
            for value in extraction.reported_financial_values
            if (
                term.metric is not None
                and value.metric_name == term.metric
                and value.period_end == period_end
            )
        ]
        reported_values = {parse_ratio(value.reported_value) for value in actuals}
        disclosures = [
            disclosure
            for disclosure in extraction.compliance_disclosures
            if (
                disclosure.covenant_name == binding.covenant_name
                and disclosure.assessment_date == period_end
                and disclosure.reported_result is not None
            )
        ]
        reported_values.update(
            parse_ratio(disclosure.reported_result) for disclosure in disclosures
        )
        if len(reported_values) > 1:
            raise ValueError("Conflicting source-reported covenant actuals.")
        source_evidence = [term.evidence, schedule.evidence]
        source_evidence.extend(event.evidence for event in applicable_events)
        reported_evidence = [value.evidence for value in actuals]
        reported_evidence.extend(disclosure.evidence for disclosure in disclosures)
        markdown = (self.service.markdown_dir / f"{binding.document_id}.md").read_text(
            encoding="utf-8",
        )
        for evidence in source_evidence + reported_evidence:
            if (
                evidence.document_id != binding.document_id
                or evidence.citation != document.citation
                or not evidence.evidence_quote.strip()
                or evidence.evidence_quote not in markdown
            ):
                raise ValueError("Selected covenant evidence does not match its stored document.")
        rules = binding.calculation_rules
        values = {} if rules is None else rules.model_dump()
        return ResolvedCovenant(
            borrower_id=binding.borrower_id,
            agreement_id=binding.agreement_id,
            covenant_id=binding.covenant_id,
            covenant_name=term.covenant_name,
            covenant_type=term.covenant_type,
            covenant_version=f"{document.cache_key}:{term.amendment_reference or 'source'}",
            period_end=period_end,
            threshold=parse_ratio(schedule.threshold),
            operator=term.operator,
            testing_status=testing_status,
            available_at=binding.available_at,
            reported_actual=next(iter(reported_values)) if reported_values else None,
            reported_evidence=[evidence.model_dump(mode="json") for evidence in reported_evidence],
            evidence=[evidence.model_dump(mode="json") for evidence in source_evidence],
            **values,
        )
