"""Judge the three main scenarios using a direct async LLM call."""

import pytest
from criteria_helpers import assert_criteria


@pytest.mark.asyncio
async def test_missing_financial_inputs(credit_agent):
    response = await credit_agent.ask_async(
        "Assess SYN010's fixed charge coverage covenant. Reporting date: 2025-09-30. "
        "Information cutoff: 2025-09-30. Explain whether the covenant is active and "
        "whether compliance can be determined.",
        borrower_id="SYN010",
    )
    print(response)
    await assert_criteria(
        response,
        [
            "The agent calls get_financials before assess_covenants, with both period_end "
            "and information_cutoff equal to 2025-09-30 for both calls, "
            "and does not call predict_risk.",
            "The answer explains that 20% revolver availability is below the 25% activation "
            "threshold, so the FCCR covenant is active, "
            "and reports its minimum requirement as 1.15x.",
            "The answer explains that compliance is incomplete because required financial inputs "
            "are missing. It invents no actual FCCR or headroom, claims neither compliance nor "
            "breach, and does not claim an actual FCCR of 1.10x.",
        ],
    )


@pytest.mark.asyncio
async def test_missing_dates(credit_agent):
    response = await credit_agent.ask_async(
        "Is SYN002 okay? Use the latest numbers.", borrower_id="SYN002"
    )
    print(response)
    await assert_criteria(
        response,
        [
            "The answer explicitly asks the analyst to provide BOTH the reporting date "
            "and the information cutoff before assessing SYN002.",
            "The agent makes no tool calls before asking for the missing dates, does not "
            "guess a date or quarter from 'latest', and reports no current compliance "
            "conclusion, ratio, or headroom.",
        ],
    )


@pytest.mark.asyncio
async def test_unavailable_forecast(credit_agent):
    response = await credit_agent.ask_async(
        "What is SYN002's probability of breaching next quarter? Reporting date: 2025-09-30. "
        "Information cutoff: 2025-09-30. Explain whether the configured model provides a forecast.",
        borrower_id="SYN002",
    )
    print(response)
    await assert_criteria(
        response,
        [
            "The agent calls get_financials before predict_risk, with both period_end and "
            "information_cutoff equal to 2025-09-30 for both calls.",
            "The answer identifies the configured model as a stub and explains that no "
            "next-quarter breach probability is available. It invents no probability, does "
            "not interpret null as 0% risk, and does not present confidence as breach probability.",
            "The answer distinguishes unavailable future risk from current compliance: SYN002 "
            "is currently compliant, with leverage approximately 5.1923x, a maximum of 5.5x, "
            "and positive headroom approximately 0.3077x. Sensible rounding such as 5.19x "
            "and 0.31x is acceptable. "
            "Current compliance is not presented as low or zero future risk.",
        ],
    )
