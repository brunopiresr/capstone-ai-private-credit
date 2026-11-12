"""Structured answer data is rendered consistently, without evidence enforcement."""

import asyncio
import json
from pathlib import Path

from markdown_it import MarkdownIt
from model_helpers import ScriptedModel, model_response

from credit_monitoring.agents.answer_contract import render_content
from credit_monitoring.agents.credit_assessment import CreditAssessmentAgent
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


def test_plain_source_markdown_stays_literal():
    text = "# Source heading\n1. list\n- bullet\n> quote\n| a | b |\n```code```"
    rendered = render_content(AnswerDraft(findings=[AnswerFinding(text=text)]))
    html = MarkdownIt().enable("table").render(rendered.answer)
    assert all(
        tag not in html for tag in ("<h1>", "<ol>", "<ul>", "<blockquote>", "<table>", "<code>")
    )
    assert "# Source heading" in html and "1. list" in html


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
            answer="There are 2 gaps.",
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
