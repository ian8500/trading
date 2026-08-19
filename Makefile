SHELL := /bin/sh
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: setup dev logs stop test lint typecheck secret-scan backtest-smoke backtest-real data-real frontend-test frontend-build migrate

setup:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'
	$(PYTHON) -m pre_commit install
	cd frontend && npm ci

dev:
	docker compose up --build -d

logs:
	docker compose logs -f backend frontend

stop:
	docker compose down

test:
	$(PYTHON) -m pytest backend/tests
	cd frontend && npm test -- --run

lint:
	$(PYTHON) -m ruff check backend scripts alembic/env.py
	$(PYTHON) -m ruff format --check backend scripts alembic/env.py
	cd frontend && npm run lint

typecheck:
	$(PYTHON) -m mypy backend/app
	cd frontend && npm run typecheck

secret-scan:
	./scripts/secret-scan.sh

backtest-smoke:
	$(PYTHON) scripts/run_backtest.py --preset smoke --output data/exports/smoke.json

data-real:
	$(PYTHON) scripts/import_historical.py --preset daily-core

backtest-real:
	$(PYTHON) scripts/run_backtest.py --preset official-daily --output data/exports/official-daily.json

frontend-test:
	cd frontend && npm test -- --run

frontend-build:
	cd frontend && npm run build

migrate:
	$(PYTHON) -m alembic upgrade head
