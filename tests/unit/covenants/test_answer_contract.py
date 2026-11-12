"""Structured answer data is rendered consistently, without evidence enforcement."""

import asyncio
import json
from pathlib import Path

import pytest
from markdown_it import MarkdownIt
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.answer_contract import render_content
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
from credit_monitoring.agents.run_state import AgentRunState
from credit_monitoring.domain.agent import (
    AgentAnswer,
    AnswerDraft,
    AnswerFinding,
    AnswerTable,
    AnswerTableRow,
    SourceReference,
)


def test_matrix_escapes_source_text_and_preserves_questions_and_numbers():
    source = SourceReference(document_id="DOC_A", citation="Section [a]_notes | $10")
    draft = AnswerDraft(
        summary="There are 2 unresolved differences.",
        findings=[AnswerFinding(text="Actual 4.77x; limit 5.50x.", citations=[source])],
        tables=[
            AnswerTable(
                title="Evidence matrix",
                columns=["Period", "Source wording"],
                rows=[
                    AnswerTableRow(
                        cells=["2025-09-30", "A | B\n$10 and $20; **bold** <script>x</script>"],
                        citations=[source],
                    ),
                ],
            )
        ],
        gaps=["Applicability remains unresolved."],
        diligence_questions=["Which amendment applies?", "What does clause [a] mean?"],
        confidence="medium",
        confidence_explanation="Conflicting sources.",
    )
    rendered = render_content(draft)
    html = MarkdownIt().enable("table").render(rendered.answer)
    assert html.count("<table>") == 1 and html.count("<td>") == 3
    assert "A | B<br>" in html and "$10 and $20" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<strong>bold</strong>" not in html
    assert "DOC_A: Section [a]_notes | $10" in html
    assert "Actual 4.77x; limit 5.50x." in html
    assert "There are 2 unresolved differences." in html
    assert html.count("<ol>") == 1 and html.count("<li>") == 3
    assert draft.tables[0].rows[0].cells[1].startswith("A | B\n")
    assert rendered.schema_version == "agent-answer-v3"
    answer = AgentAnswer(**rendered.model_dump())
    assert AgentAnswer.model_validate_json(answer.model_dump_json()) == answer


def test_incomplete_streaming_table_preserves_all_supplied_cells():
    draft = AnswerDraft(
        tables=[
            AnswerTable(
                columns=["Metric"],
                rows=[
                    AnswerTableRow(cells=["Leverage", "5.5x"]),
                    AnswerTableRow(cells=["Coverage"]),
                ],
            )
        ]
    )
    html = MarkdownIt().enable("table").render(render_content(draft).answer)
    assert "5.5x" in html and "Coverage" in html and "Column 2" in html
    assert html.count("<td>") == 4


def test_narrative_markdown_renders_and_citation_remains_outside_blocks():
    text = (
        "### Assessment\n\n**Leverage** is *within limits*.\n\n"
        "1. Review actuals\n2. Confirm terms\n\n- Follow up\n\n"
        "> Source-reported result\n\n"
        "[Filing](https://example.invalid/filing?a=1&b=2)\n\n"
        "```text\n<script>$10 & $20</script>\n```"
    )
    source = SourceReference(document_id="DOC_A", citation="**literal** [a] | $10")
    draft = AnswerDraft(
        summary="**Result:** review required.",
        findings=[AnswerFinding(text=text, citations=[source])],
        confidence="medium",
        confidence_explanation="Limited evidence.",
    )
    rendered = render_content(draft)
    html = MarkdownIt().enable("table").render(rendered.answer)
    assert all(tag in html for tag in ("<h3>", "<strong>", "<em>", "<ol>", "<ul>", "<blockquote>"))
    assert 'href="https://example.invalid/filing?a=1&amp;b=2"' in html
    assert "&lt;script&gt;$10 &amp; $20&lt;/script&gt;" in html
    assert "</pre>\n<p>Source: DOC_A: **literal** [a] | $10</p>" in html
    assert rendered.confidence_explanation == draft.confidence_explanation
    assert rendered.confidence_explanation not in rendered.answer
    assert rendered.findings == draft.findings and rendered.summary == draft.summary


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "<script>alert('x')</script> **safe**",
            "&lt;script&gt;alert('x')&lt;/script&gt; <strong>safe</strong>",
        ),
        ("<img src=x onerror=alert(1)>", "&lt;img src=x onerror=alert(1)&gt;"),
        ("$10 and $20; already \\$30", "$10 and $20; already $30"),
        ("Actual < 5x and > 2x", "Actual &lt; 5x and &gt; 2x"),
        ("`<script>$10 & $20</script>`", "<code>&lt;script&gt;$10 &amp; $20&lt;/script&gt;</code>"),
        ("``literal ` and $10``", "<code>literal ` and $10</code>"),
        ("`\n\n<script>x</script>\n\n`", "&lt;script&gt;x&lt;/script&gt;"),
        ("`\n# <script>x</script>\n`", "&lt;script&gt;x&lt;/script&gt;"),
        (r"\`<script>x</script>`", "&lt;script&gt;x&lt;/script&gt;"),
        ("<https://example.invalid/?a=1&b=2>", 'href="https://example.invalid/?a=1&amp;b=2"'),
    ],
)
def test_narratives_preserve_markdown_code_currency_and_escape_html(text, expected):
    rendered = render_content(AnswerDraft(summary=text))
    html = MarkdownIt().render(rendered.answer)
    assert expected in html
    assert "<script>" not in html and "<img " not in html
    if text.startswith("$10"):
        assert rendered.answer == r"\$10 and \$20; already \$30"


@pytest.mark.parametrize("fence", ["```", "~~~~"])
@pytest.mark.parametrize("closed", [False, True])
def test_fenced_code_preserves_literals_and_cannot_swallow_citations(fence, closed):
    text = fence + "text\n<script>$10 & $20</script>\n" + (fence if closed else "")
    rendered = render_content(
        AnswerDraft(
            findings=[
                AnswerFinding(
                    text=text, citations=[SourceReference(document_id="DOC", citation="Section 1")]
                )
            ],
            gaps=["Still **unknown**."],
        )
    )
    html = MarkdownIt().render(rendered.answer)
    assert "&lt;script&gt;$10 &amp; $20&lt;/script&gt;" in html
    assert "</pre>\n<p>Source: DOC: Section 1</p>" in html
    assert "<h3>Gaps and limitations</h3>" in html
    assert "<strong>unknown</strong>" in html


def test_multiline_gap_and_tenth_question_keep_nested_blocks_in_the_item():
    question = "Confirm **terms**?\n\n- First source\n- Second source\n\n```text\n$10 < $20\n```"
    rendered = render_content(
        AnswerDraft(
            gaps=["Missing **filing**.\n\n- Request it\n- Check dates"],
            diligence_questions=[f"Question {i}?" for i in range(1, 10)] + [question],
        )
    )
    html = MarkdownIt().render(rendered.answer)
    assert "<strong>filing</strong>" in html
    assert html.count("<ol>") == 1
    assert "<li>\n<p>Confirm <strong>terms</strong>?</p>\n<ul>" in html
    assert '<code class="language-text">$10 &lt; $20\n</code></pre>\n</li>\n</ol>' in html
    assert "10. Confirm **terms**?\n    \n    - First source" in rendered.answer


def test_nested_and_indented_code_preserve_content_without_exposing_following_html():
    text = (
        "- item\n  ```text\n  $10 < $20\n    ```\n\n<script>outside</script>\n\n"
        "    <script>literal code</script>\n"
    )
    html = MarkdownIt().render(render_content(AnswerDraft(summary=text)).answer)
    assert '<code class="language-text">$10 &lt; $20\n</code>' in html
    assert "<pre><code>&lt;script&gt;literal code&lt;/script&gt;" in html
    assert "&lt;script&gt;outside&lt;/script&gt;" in html and "<script>" not in html


def test_failure_text_stays_literal():
    message = "# Model failure\n<script>x</script> **diagnostic** $10"
    answer = AgentRunState(max_tool_rounds=1).answer(message, "model_error")
    html = MarkdownIt().render(answer.answer)
    assert not answer.complete and answer.summary == message
    assert "<h1>" not in html and "<strong>" not in html and "<script>" not in html
    assert "**diagnostic** $10" in html and "&lt;script&gt;" in html


def test_supplied_citations_are_formatted_without_membership_or_claim_checks(
    document_service_factory,
):
    model = ScriptedModel(
        response=model_response(
            answer="A numeric explanation survives: 2 observations.",
            findings=[
                {
                    "text": "Reported ratio 99x.",
                    "citations": [
                        {"document_id": "MODEL_SUPPLIED", "citation": "Section 7"},
                    ],
                }
            ],
        )
    )
    answer = CreditAssessmentAgent(service=document_service_factory(), model=model).ask("Explain")
    assert answer.complete and model.respond.call_count == 1
    assert "99x" in answer.answer and "MODEL" in answer.answer and "Section 7" in answer.answer
    assert "2 observations" in answer.answer and answer.evidence == []


def test_stream_and_final_use_same_renderer(document_service_factory):
    model = ScriptedModel(
        response=model_response(
            answer="There are **2 gaps**.",
            tables=[
                {
                    "title": "Matrix",
                    "columns": ["Source"],
                    "rows": [{"cells": ["A | B\n$20"]}],
                }
            ],
            diligence_questions=["Can you provide the missing source?"],
        )
    )
    agent = CreditAssessmentAgent(service=document_service_factory(), model=model)

    async def collect():
        return [event async for event in agent.stream_async("Prepare a matrix")]

    events = asyncio.run(collect())
    updates = [event.output for event in events if event.kind == "answer_update"]
    assert updates and updates[-1].answer == events[-1].answer.answer
    assert events[-1].answer.tables and events[-1].answer.diligence_questions
    assert "<strong>2 gaps</strong>" in MarkdownIt().render(updates[-1].answer)


def test_historical_v2_answers_and_claims_load_unchanged():
    path = Path(
        "data/evaluation/agent_scenarios/results/2026-11-09-poc-final/cases/H01/answer.json"
    )
    raw = json.loads(path.read_text())
    answer = AgentAnswer.model_validate(raw)
    assert answer.answer == raw["answer"] and answer.schema_version == "agent-answer-v2"
    assert answer.claims and not answer.tables
    legacy = AgentAnswer.model_validate_json('{"answer":"Old uncited answer"}')
    assert legacy.schema_version is None and legacy.findings == []
    v3 = AgentAnswer.model_validate_json(
        r'{"answer":"Existing \\*\\*literal\\*\\*", "schema_version":"agent-answer-v3"}'
    )
    assert v3.answer == r"Existing \*\*literal\*\*"
