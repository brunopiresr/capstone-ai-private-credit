"""Versioned grouping directive for the single-request batch extractor."""

from .extraction import EXTRACTION_INSTRUCTIONS

BATCH_PROMPT_VERSION = "sec-covenant-batch-v2.1"
BATCH_GROUPING_INSTRUCTIONS = """
For this batch request, apply CovenantExtraction separately to every company
in the supplied catalog. Return AllCompanyCovenantExtraction as the outer
wrapper, with a complete CovenantExtraction in each company's extraction field.
Copy company and ticker from the supplied catalog and include exactly one
entry per catalog ticker, even when its evidence is sparse or absent.
Keep each company's evidence, historical versions, gaps and conflicts separate.
Use only that company's records for its evidence. The batch summary must contain
only source-supported facts, with no calculations or governing-term conclusions.
Catalog notes are descriptions, not filing evidence or proof of a covenant.
"""

ALL_COMPANY_INSTRUCTIONS = EXTRACTION_INSTRUCTIONS + "\n" + BATCH_GROUPING_INSTRUCTIONS
