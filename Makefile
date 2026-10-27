.PHONY: install run lint format test test-offline test-homework test-all test-ml test-judges lint-judges check check-all

install:
	uv sync --group dev --locked

run:
	uv run --locked streamlit run src/credit_monitoring/web/app.py

lint:
	uv run --locked ruff check .

format:
	uv run --locked ruff format .

test: test-offline

test-offline:
	uv run --locked pytest tests

test-homework:
	uv run --locked pytest homework/agent-tests homework/monitoring/tests homework/notebooks/tests homework/evaluation/2026-10-26/test_workbench.py

test-all: test-offline test-homework

test-ml:
	uv run --locked --extra ml pytest tests/integration/workflows/test_model_training.py

test-judges:
	uv run --project homework/llm-judges --locked python -m pytest -c homework/llm-judges/pyproject.toml homework/llm-judges/tests

lint-judges:
	uv run --project homework/llm-judges --locked python -m ruff check --config homework/llm-judges/pyproject.toml homework/llm-judges/src homework/llm-judges/tests

check: lint test-all

check-all: check test-ml lint-judges test-judges
