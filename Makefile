.PHONY: install lint format test test-offline test-homework test-ml test-judges lint-judges check

install:
	uv sync --group dev --locked

lint:
	uv run --locked ruff check .

format:
	uv run --locked ruff format .

test: test-offline

test-offline:
	uv run --locked pytest tests homework-tests

test-homework:
	uv run --locked pytest homework-tests

test-ml:
	uv run --locked --extra ml pytest tests/integration/workflows/test_model_training.py

test-judges:
	uv run --project tools/llm_judges --locked pytest -c tools/llm_judges/pyproject.toml tools/llm_judges/tests

lint-judges:
	uv run --project tools/llm_judges --locked ruff check --config tools/llm_judges/pyproject.toml tools/llm_judges/src tools/llm_judges/tests

check: lint test-offline test-ml lint-judges test-judges
