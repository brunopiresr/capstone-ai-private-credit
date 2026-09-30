.PHONY: install lint format test

install:
	uv sync --group dev

lint:
	uv run ruff check .

format:
	uv run ruff format .

test:
	uv run pytest
