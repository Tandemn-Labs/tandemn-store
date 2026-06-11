.PHONY: help up down logs ps install precommit-install precommit-run test \
        test-integration lint format clean migrate migrate-down migrate-check \
        migrate-new contracts

help:
	@echo "tandemn-store dev targets:"
	@echo "  make up                  start Postgres + MinIO via docker-compose"
	@echo "  make down                stop the stack"
	@echo "  make logs                follow stack logs"
	@echo "  make ps                  show stack status"
	@echo "  make install             create venv and install deps via uv"
	@echo "  make precommit-install   install pre-commit git hooks"
	@echo "  make precommit-run       run pre-commit hooks on all files"
	@echo "  make test                run unit tests (no infra required)"
	@echo "  make test-integration    run integration tests (requires \`make up\`)"
	@echo "  make migrate             alembic upgrade head"
	@echo "  make migrate-down        alembic downgrade base"
	@echo "  make migrate-check       alembic check (no diff vs ORM)"
	@echo "  make migrate-new M=msg   alembic revision --autogenerate -m \"msg\""
	@echo "  make lint                ruff check"
	@echo "  make format              ruff format"
	@echo "  make contracts           import-linter (boundary between the two packages)"
	@echo "  make clean               remove .venv and __pycache__ trees"

up:
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@docker compose ps

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

install:
	uv sync --extra dev

precommit-install:
	uv run pre-commit install

precommit-run:
	uv run pre-commit run --all-files

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

contracts:
	uv run lint-imports

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade base

migrate-check:
	uv run alembic check

migrate-new:
	@if [ -z "$(M)" ]; then echo "usage: make migrate-new M=\"short message\""; exit 1; fi
	uv run alembic revision --autogenerate -m "$(M)"

clean:
	rm -rf .venv .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
