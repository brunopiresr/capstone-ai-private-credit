"""Build comparable features from one persisted assessment run."""

from datetime import date

from credit_monitoring.calculations.trends import difference, growth, previous_period
from credit_monitoring.domain.assessment import CovenantResult, FinancialPeriod
from credit_monitoring.domain.risk_features import BorrowerRiskFeatures, CovenantRiskFeatures
from credit_monitoring.observability.assessment import resolution_context
from credit_monitoring.observability.logging import logged_operation, logging_context
from credit_monitoring.persistence.analytics_repositories import CovenantResultRepository


def _financial_period(result: CovenantResult) -> FinancialPeriod:
    return FinancialPeriod.model_validate(result.financial_inputs["financial_period"])


def _comparable(current: CovenantResult, prior: CovenantResult) -> bool:
    if current.resolved_covenant is None or prior.resolved_covenant is None:
        return False
    return (
        current.agreement_id == prior.agreement_id
        and current.resolved_covenant.basis_key == prior.resolved_covenant.basis_key
        and current.operator == prior.operator
        and current.financial_inputs["result_basis"] == prior.financial_inputs["result_basis"]
    )


class RiskFeatureBuilder:
    """Read stored calculation inputs instead of mutable financial rows or raw documents."""

    def __init__(self, result_repository: CovenantResultRepository) -> None:
        self.result_repository = result_repository

    @logged_operation(
        inputs=resolution_context,
        outputs=lambda features: {"features": features.model_dump(mode="json")},
        context=lambda args: {
            **resolution_context(args),
            "assessment_run_id": args["assessment_run_id"],
        },
    )
    def build(
        self,
        borrower_id: str,
        period_end: date,
        information_cutoff: date,
        *,
        assessment_run_id: str,
    ) -> BorrowerRiskFeatures:
        """Build one vector; prior quarter/year dates must exist explicitly."""
        results = self.result_repository.get_history(
            borrower_id,
            period_end=period_end,
            information_cutoff=information_cutoff,
            assessment_run_id=assessment_run_id,
        )
        current_results = [result for result in results if result.period_end == period_end]
        if not current_results:
            raise ValueError("Persist current covenant results before constructing risk features.")
        indexed = {(result.covenant_id, result.period_end): result for result in results}
        quarter_end = previous_period(period_end)
        covenant_features = []
        for current in current_results:
            with logging_context(
                covenant_id=current.covenant_id, comparison_period_end=quarter_end
            ):
                prior = indexed.get((current.covenant_id, quarter_end))
                features = CovenantRiskFeatures(
                    covenant_id=current.covenant_id,
                    covenant_type=current.covenant_type,
                    actual_value=current.actual_value,
                    threshold=current.threshold,
                    headroom=current.headroom,
                    compliance_status=current.compliance_status,
                )
                if prior is not None:
                    if prior.compliance_status in ("compliant", "breach"):
                        features.previous_breach = prior.compliance_status == "breach"
                    if (
                        prior.resolved_covenant
                        and prior.resolved_covenant.testing_status != "unresolved"
                    ):
                        features.previous_waiver = (
                            prior.resolved_covenant.testing_status == "waived"
                        )
                    comparable = _comparable(current, prior)
                    features.basis_changed = not comparable
                    if comparable:
                        features.threshold_change_qoq = difference(
                            current.threshold, prior.threshold
                        )
                        if current.compliance_status in ("compliant", "breach") and (
                            prior.compliance_status in ("compliant", "breach")
                        ):
                            features.metric_change_qoq = difference(
                                current.actual_value, prior.actual_value
                            )
                            features.headroom_change_qoq = difference(
                                current.headroom, prior.headroom
                            )
                covenant_features.append(features)
        periods = {result.period_end: _financial_period(result) for result in results}
        current_financials = periods[period_end]
        vector = BorrowerRiskFeatures(
            borrower_id=borrower_id,
            period_end=period_end,
            information_cutoff=information_cutoff,
            covenants=covenant_features,
            information_availability_known=all(
                _financial_period(result).available_at is not None
                and result.resolved_covenant is not None
                and result.resolved_covenant.available_at is not None
                for result in results
            ),
        )
        for suffix, quarters in (("qoq", 1), ("yoy", 4)):
            prior_financials = periods.get(previous_period(period_end, quarters))
            if prior_financials is None:
                continue
            if (
                current_financials.source_file != prior_financials.source_file
                or current_financials.currency != prior_financials.currency
                or current_financials.scale != prior_financials.scale
            ):
                continue
            for metric in ("reported_ebitda", "total_debt"):
                with logging_context(metric=metric, trend=suffix):
                    setattr(
                        vector,
                        f"{metric}_growth_{suffix}",
                        growth(
                            current_financials.metrics.get(metric),
                            prior_financials.metrics.get(metric),
                        ),
                    )
        return BorrowerRiskFeatures.model_validate(vector.model_dump())
