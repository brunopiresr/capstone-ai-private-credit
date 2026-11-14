"""Run with: uv run --locked streamlit run homework/feedback-eval/app.py."""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend as be  # noqa: E402

load_dotenv(be.ROOT / ".env")
st.set_page_config(page_title="Logs → ground truth → eval", page_icon="🧪", layout="wide")
st.title("Logs → ground truth → eval")
st.caption(
    "A small local playground: review real cases, save references, compare prompts or models."
)

dataset = be.DATA / "cases.jsonl"
cases = be.load_cases(dataset)


def merge(incoming):
    existing = {c.case_id for c in cases}
    added = [c for c in incoming if c.case_id not in existing]
    be.save_cases(dataset, cases + added)
    st.session_state["notice"] = f"Imported {len(added)} cases. Existing reviews were preserved."
    st.rerun()


if notice := st.session_state.pop("notice", None):
    st.success(notice)

left, middle, right = st.columns(3)
left.metric("Cases", len(cases))
middle.metric("Approved references", sum(c.status == "approved" for c in cases))
right.metric("Pending review", sum(c.status == "pending" for c in cases))

imports, review, evaluate = st.tabs(["1 · Import", "2 · Review cases", "3 · Evaluate"])

with imports:
    st.write(
        "Start with fictional examples or import your Logfire export. All imports need review."
    )
    if st.button("Load 4 demo cases"):
        merge(be.import_cases(be.DEMO.read_text()))
    upload = st.file_uploader("Import cases or Logfire records", type=["json", "jsonl"])
    if st.button("Import file", disabled=upload is None):
        try:
            incoming = be.import_cases(upload.getvalue().decode("utf-8"))
            if not incoming:
                st.warning(
                    "No reviewed interactions found. Check interaction_id and feedback records."
                )
            else:
                merge(incoming)
        except (ValueError, TypeError, KeyError) as exc:
            st.error(str(exc))
    with st.expander("Fetch from Logfire"):
        st.caption(
            "Uses LOGFIRE_READ_TOKEN from .env. Original traces are searched up to 30 days back."
        )
        with st.form("logfire"):
            start = st.date_input("From (UTC)", datetime.now(UTC).date() - timedelta(days=7))
            end = st.date_input("Through (UTC)", datetime.now(UTC).date())
            service = st.text_input("Service", "credit-monitoring")
            environment = st.text_input("Environment", "development")
            fetch = st.form_submit_button("Fetch reviewed interactions")
        if fetch:
            try:
                with st.spinner("Fetching Logfire records…"):
                    export = be.fetch_logfire(
                        datetime.combine(start, datetime.min.time(), UTC),
                        datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC),
                        service,
                        environment,
                    )
                    be.DATA.mkdir(parents=True, exist_ok=True)
                    (be.DATA / "last-logfire-export.json").write_text(json.dumps(export, indent=2))
                    incoming = be.import_cases(json.dumps(export))
                if incoming:
                    merge(incoming)
                else:
                    st.warning(
                        "No matching feedback. Try another date range, service or environment."
                    )
            except Exception as exc:
                st.error(f"Fetch failed: {type(exc).__name__}: {exc}")

with review:
    if not cases:
        st.info("Import cases first. The demo cases work without API keys.")
    else:
        chosen = st.selectbox(
            "Case", cases, format_func=lambda c: f"{c.status} · {c.case_id} · {c.question[:70]}"
        )
        st.caption(
            "Ratings help find useful examples. Check the evidence before approving a reference."
        )
        if chosen.reviews:
            st.write("**User reviews**")
            for rating in chosen.reviews:
                score = rating.get("gen_ai.evaluation.score.value", rating.get("score", "—"))
                scale = " / 1" if rating.get("feedback_type") == "quick" else " / 5"
                st.write(
                    f"{score}{scale} · {rating.get('category', 'Quick rating')} · "
                    f"{rating.get('comment', '')}"
                )
        with st.form(f"review-{chosen.case_id}"):
            question = st.text_area("Question", chosen.question)
            a, b = st.columns(2)
            with a:
                answer = st.text_area("Captured answer", chosen.answer, height=220)
                st.caption(
                    "Structured outputs may be raw JSON. Check the original trace if needed."
                )
            with b:
                evidence = st.text_area(
                    "Source evidence / replay context", chosen.evidence, height=220
                )
                st.caption(
                    "Include source IDs, facts, dates and any prior context needed to answer."
                )
            expected = st.text_area(
                "Expected answer / required behavior", chosen.expected, height=150
            )
            a, b, c = st.columns(3)
            reviewer = a.text_input("Reviewer", chosen.reviewer)
            split = b.selectbox(
                "Split", ["dev", "holdout"], index=["dev", "holdout"].index(chosen.split)
            )
            status = c.selectbox(
                "Status",
                ["pending", "approved", "excluded"],
                index=["pending", "approved", "excluded"].index(chosen.status),
            )
            group = st.text_input("Related-case group", chosen.group or chosen.case_id)
            st.caption(
                "Keep related turns and paraphrases in one split. Holdout is for a final check."
            )
            save = st.form_submit_button("Save review", type="primary")
        if save:
            updated = chosen.model_copy(
                update={
                    "question": question.strip(),
                    "answer": answer.strip(),
                    "evidence": evidence.strip(),
                    "expected": expected.strip(),
                    "reviewer": reviewer.strip(),
                    "split": split,
                    "status": status,
                    "group": group.strip(),
                    "reviewed_at": datetime.now(UTC).isoformat() if status == "approved" else "",
                }
            )
            try:
                be.save_cases(
                    dataset, [updated if c.case_id == chosen.case_id else c for c in cases]
                )
                st.session_state["notice"] = "Review saved."
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        with st.expander("Original provenance"):
            st.json(chosen.provenance)
        st.download_button("Download reviewed dataset", dataset.read_text(), "cases.jsonl")

with evaluate:
    st.write(
        "Fresh answers use the same source context. Expected answers stay hidden from generation."
    )
    st.caption("This tests answers using captured evidence. It does not replay application tools.")
    with st.form("experiment"):
        captured = st.checkbox("Grade captured answers only (diagnosis, no fresh generation)")
        split = st.selectbox("Evaluate split", ["dev", "holdout"])
        a, b = st.columns(2)
        with a:
            st.write("**Baseline**")
            baseline_model = st.text_input("Baseline model", be.MODEL)
            baseline_prompt = st.text_area("Baseline prompt", be.BASELINE, height=150)
        with b:
            st.write("**Candidate**")
            candidate_model = st.text_input("Candidate model", be.MODEL)
            candidate_prompt = st.text_area("Candidate prompt", be.CANDIDATE, height=150)
        judge_model = st.text_input("Judge model (fixed for both)", be.MODEL)
        st.caption(
            "Uses OPENAI_API_KEY from .env. Up to 30 approved cases; "
            "fresh comparisons make at most 4 model requests per case. Requests are paid."
        )
        run = st.form_submit_button("Run evaluation", type="primary")
    if run:
        configs = [
            {
                "name": "Captured" if captured else "Baseline",
                "model": baseline_model,
                "prompt": baseline_prompt,
            }
        ]
        if not captured:
            configs.append(
                {"name": "Candidate", "model": candidate_model, "prompt": candidate_prompt}
            )
        try:
            with st.spinner("Generating and judging answers…"):
                folder = asyncio.run(
                    be.run_evaluation(cases, configs, judge_model, split=split, captured=captured)
                )
            st.session_state["saved_run"] = folder
            st.success("Evaluation saved.")
        except Exception as exc:
            st.error(str(exc))
    runs = sorted((be.DATA / "runs").glob("*/summary.json"), reverse=True)
    if runs:
        selected = st.selectbox(
            "Saved run", [p.parent for p in runs], format_func=lambda p: p.name, key="saved_run"
        )
        manifest = json.loads((selected / "manifest.json").read_text())
        st.caption(
            f"{manifest['mode']} · {manifest['split']} · "
            f"dataset {manifest['dataset_hash'][:12]} · uncalibrated LLM judge"
        )
        st.dataframe(
            json.loads((selected / "summary.json").read_text()), hide_index=True, width="stretch"
        )
        results = [
            json.loads(line) for line in (selected / "results.jsonl").read_text().splitlines()
        ]
        for case in manifest["cases"]:
            with st.expander(f"{case['case_id']} · {case['question']}"):
                columns = st.columns(len(manifest["configs"]))
                for column, config in zip(columns, manifest["configs"], strict=True):
                    row = next(
                        r
                        for r in results
                        if r["case_id"] == case["case_id"] and r["configuration"] == config["name"]
                    )
                    with column:
                        st.write(f"**{config['name']} · {row['label']}**")
                        st.write(row["answer"])
                        st.caption(row["reason"])
        if manifest["mode"] == "fresh":
            decision_file = selected / "decision.json"
            decision = json.loads(decision_file.read_text()) if decision_file.exists() else {}
            with st.form(f"decision-{selected.name}"):
                preference = st.selectbox(
                    "Preferred configuration", [c["name"] for c in manifest["configs"]]
                )
                reason = st.text_area("Why keep this configuration?", decision.get("reason", ""))
                if st.form_submit_button("Save tuning decision"):
                    if reason.strip():
                        decision_file.write_text(
                            json.dumps(
                                {"configuration": preference, "reason": reason.strip()}, indent=2
                            )
                        )
                        st.success("Tuning decision saved alongside this run.")
                    else:
                        st.error("Add a reason based on the comparison.")
        st.download_button(
            "Download comparison report", (selected / "REPORT.md").read_text(), "REPORT.md"
        )

st.caption("Local demo · saved in data/runtime/feedback-eval · application code stays unchanged")
