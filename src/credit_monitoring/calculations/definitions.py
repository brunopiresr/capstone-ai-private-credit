"""Display the economic definition belonging to the applied calculation contract."""

from credit_monitoring.domain.assessment import ResolvedCovenant

FORMULAS = {
    "total_leverage": "Total leverage = contractual debt / covenant EBITDA",
    "net_leverage": "Net leverage = (contractual debt − eligible cash) / covenant EBITDA",
    "pro_forma_leverage": "Pro forma leverage = contractual debt / pro forma covenant EBITDA",
    "interest_coverage": "Interest coverage = covenant EBITDA / cash interest",
    "fixed_charge_coverage": (
        "Fixed-charge coverage = (covenant EBITDA − capex − cash taxes) / "
        "(cash interest + scheduled principal + rent)"
    ),
}


def describe_formula(covenant: ResolvedCovenant) -> str:
    if covenant.calculation_contract == "bundle_v1":
        ratio = {
            "total_leverage": "Total leverage = total debt / adjusted EBITDA",
            "net_leverage": "Net leverage = max(0, debt − eligible capped cash) / adjusted EBITDA",
            "interest_coverage": "Interest coverage = adjusted EBITDA / TTM interest expense",
            "fixed_charge_coverage": (
                "Fixed-charge coverage = supplied numerator / supplied fixed charges"
            ),
        }.get(covenant.formula, "Unsupported formula")
        return (
            ratio + "\nAdjusted EBITDA = base EBITDA + eligible capped addbacks + "
            "acquired EBITDA + eligible capped synergies\n"
            "Adjustment caps use max(base EBITDA, 0)."
        )
    return FORMULAS.get(covenant.formula, "Unsupported formula")
