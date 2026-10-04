"""Schema/default checks using controlled synthetic facts."""

from datetime import date

import pytest
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import ValidationError

from credit_monitoring import domain
from credit_monitoring.domain import (
    AgreementAmendment,
    AllCompanyCovenantExtraction,
    ComplianceDisclosure,
    CovenantExtraction,
    CovenantTerm,
    CovenantTestingEvent,
    FinancialMetricDefinition,
    ReportedFinancialValue,
    SourceEvidence,
    ThresholdScheduleEntry,
)


def test_every_exported_model_field_has_a_description():
    for name in domain.__all__:
        model = getattr(domain, name)
        for field in model.model_fields.values():
            assert field.description and field.description.strip(), (name, field)


@pytest.mark.parametrize("model", [CovenantExtraction, AllCompanyCovenantExtraction])
def test_installed_sdk_builds_strict_json_schema(model):
    format_param = type_to_text_format_param(model)
    assert format_param["strict"] is True
    schema = format_param["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    for child in schema.get("$defs", {}).values():
        if child.get("type") == "object":
            assert child["additionalProperties"] is False
            assert set(child["required"]) == set(child["properties"])


def test_optional_defaults_and_independent_collections(synthetic_records, evidence_for):
    first, second = CovenantExtraction(), CovenantExtraction()
    first.gaps.append("Synthetic missing threshold")
    assert second.gaps == []
    for field in ("issuer", "ticker", "borrower"):
        assert getattr(second, field) is None
    for name, field in CovenantExtraction.model_fields.items():
        if field.default_factory is list:
            assert getattr(second, name) == []
    evidence = evidence_for(synthetic_records["base"])
    term = CovenantTerm(covenant_name="Total Leverage", covenant_type="leverage", evidence=evidence)
    assert term.operator is None and term.threshold_direction == "not_stated"
    assert term.threshold_schedule == [] and term.metric_definition_name is None
    entry = ThresholdScheduleEntry(threshold="5.00 to 1.00", evidence=evidence)
    assert entry.period_end_dates == []
    assert entry.from_period_end is None and entry.through_period_end is None
    assert entry.measurement_basis is None


@pytest.mark.parametrize(
    "values",
    [
        {"covenant_type": "invented"},
        {"operator": "approximately"},
        {"threshold_direction": "unknown"},
        {"reported_result": "calculated old field"},
    ],
)
def test_invalid_or_old_covenant_fields_are_rejected(values, synthetic_records, evidence_for):
    kwargs = {
        "covenant_name": "Total Leverage",
        "covenant_type": "leverage",
        "evidence": evidence_for(synthetic_records["base"]),
    }
    with pytest.raises(ValidationError):
        CovenantTerm.model_validate({**kwargs, **values})


def test_source_evidence_is_required():
    with pytest.raises(ValidationError):
        ThresholdScheduleEntry(threshold="5.00")
    with pytest.raises(ValidationError):
        SourceEvidence(evidence_quote="synthetic")


@pytest.mark.parametrize(
    "model,kwargs",
    [
        (AgreementAmendment, {"execution_date": "2025-02-01"}),
        (CovenantTestingEvent, {"covenant_name": "Total Leverage", "event_type": "waiver"}),
        (
            ComplianceDisclosure,
            {"status": "deemed_compliant", "description": "Synthetic disclosure"},
        ),
        (FinancialMetricDefinition, {"name": "Consolidated EBITDA"}),
        (
            ReportedFinancialValue,
            {"metric_name": "Consolidated EBITDA", "reported_value": "$24.000 million"},
        ),
    ],
)
def test_other_contracts_validate_and_serialize(model, kwargs, synthetic_records, evidence_for):
    value = model(**kwargs, evidence=evidence_for(synthetic_records["base"]))
    assert model.model_validate_json(value.model_dump_json()) == value
    if isinstance(value, AgreementAmendment):
        assert value.execution_date == date(2025, 2, 1)
        assert value.stated_effective_date is None
