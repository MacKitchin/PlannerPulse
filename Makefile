.PHONY: help install dev test lint format clean run gen migrate db-upgrade db-downgrade docker-build docker-up docker-down

# Default target
help:
	@echo "PlannerPulse - Newsletter Generation System"
	@echo ""
	@echo "Available targets:"
	@echo "  make install       - Install production dependencies"
	@echo "  make dev           - Install development dependencies"
	@echo "  make run           - Start Flask web server"
	@echo "  make gen           - Generate newsletter (CLI)"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run linters (ruff)"
	@echo "  make format        - Format code (ruff)"
	@echo "  make clean         - Remove generated files"
	@echo "  make migrate       - Create new database migration"
	@echo "  make db-upgrade    - Apply database migrations"
	@echo "  make db-downgrade  - Revert database migration"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-up     - Start Docker containers"
	@echo "  make docker-down   - Stop Docker containers"

# Installation
install:
	pip install -r requirements.txt

dev:
	pip install -r requirements.txt
	pip install ruff mypy pytest pytest-cov pytest-mock

# Run application
run:
	python app.py

gen:
	python main.py

# Testing
test:
	pytest tests/ -v --cov=. --cov-report=html --cov-report=term

# Linting and formatting
lint:
	ruff check .
	mypy . --ignore-missing-imports

format:
	ruff format .

# Database migrations
migrate:
	@read -p "Enter migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

db-upgrade:
	alembic upgrade head

db-downgrade:
	alembic downgrade -1

# Docker
docker-build:
	docker build -t plannerpulse:latest .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	@echo "Cleaned generated files"

# Validation
validate:
	@echo "Validating Python syntax..."
	python -m py_compile *.py
	@echo "All Python files are syntactically correct"
