.PHONY: install test lint fmt serve check docker clean

VENV ?= .venv
PY   := $(VENV)/bin/python

install:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -e ".[dev,documents]"

test:
	$(PY) -m pytest -q

lint:
	$(VENV)/bin/ruff check .

fmt:
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

check:
	$(VENV)/bin/harness check

serve:
	$(VENV)/bin/uvicorn nonprofit_harness.main:app --reload --port 8080

docker:
	docker build -t nonprofit-agent-harness -f deployment/Dockerfile .

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__ src/*.egg-info
