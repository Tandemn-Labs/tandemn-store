.PHONY: help up down logs ps install test test-integration lint format clean

help:
	@echo "tandemn-store dev targets:"
	@echo "  make up                  start Postgres + Redis + MinIO via docker-compose"
	@echo "  make down                stop the stack"
	@echo "  make logs                follow stack logs"
	@echo "  make ps                  show stack status"
	@echo "  make install             create venv and install deps via uv"
	@echo "  make test                run unit tests (no infra required)"
	@echo "  make test-integration    run integration tests (requires \`make up\`)"
	@echo "  make lint                ruff check"
	@echo "  make format              ruff format"
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

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

clean:
	rm -rf .venv .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
