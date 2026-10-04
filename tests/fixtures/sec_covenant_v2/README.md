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

These tests were created but not run, at the user's request.
