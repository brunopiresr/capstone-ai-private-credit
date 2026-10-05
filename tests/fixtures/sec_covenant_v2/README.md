# Controlled SEC covenant extraction fixtures

`records.json` contains labelled synthetic excerpts. They are not claims about
actual SEC filings, including the four URLs in the implementation guide.

`extraction_prompt_v2.txt` freezes the exact agreed V2 instruction string,
including leading/trailing newlines. A reviewed prompt-version update should
update this snapshot deliberately.

Unit tests construct expected structured facts from these snippets. Workflow
tests use mocked SDK responses and one mocked HTTP exchange through the installed
SDK. They verify preservation, input assembly, parsing, provenance, serialization,
and error handling; they do **not** establish live model extraction accuracy or
resistance to prompt injection. The injection test checks instruction/data isolation.

The optional local SEC regression reads an existing ignored Markdown file when
available and otherwise skips. It checks verbatim provenance without calling a model.

The original tests have been run successfully. Complete-document regression coverage
also uses `fmc_amendment_schedule.md`, a source excerpt containing all 19 leverage
and 17 interest-coverage quarters from `DOC_FMC_AMD3_2025`, including page continuation.
The source catalog links that amendment to the SEC filing. These are pipeline tests
with mocked model outputs, not live LLM accuracy evaluations.

`extraction_prompt_v2.txt` preserves the historical v2.0 prompt;
`extraction_prompt_v2_1.txt` is the active v2.1 snapshot.
