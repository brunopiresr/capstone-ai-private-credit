# Three Main Test Scenarios

**1. Missing financial data:** Ask the agent to assess SYN010 for September 30, 2025, with the same information cutoff. The covenant is active, but required financial inputs are missing. The agent should check the data and report that compliance cannot be determined, rather than inventing a ratio or declaring a breach.

**2. Missing historical cutoff:** Ask, "Assess SYN002 for reporting date 2025-09-30; what information cutoff should I supply?" The agent should ask the analyst to choose the cutoff, keeping the specified reporting period. It should not calculate or forecast. Read-only period discovery is optional. For latest/current requests without established dates, the agent may instead discover the period and disclose today's date as its default cutoff.

**3. Unavailable forecast:** Ask for SYN002's next-quarter breach probability, using September 30, 2025 as both the reporting date and information cutoff, while the configured forecasting model provides no prediction. The agent should explain that the probability is unavailable and distinguish current compliance from future risk. It should not invent a percentage or interpret a missing prediction as 0% risk.
