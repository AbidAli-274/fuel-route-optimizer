# Fuel Route Optimizer API

Django REST Framework project for a fuel-route optimization assessment.

This first milestone contains only the project bootstrap and health endpoint.

## Requirements

- Python 3.12+

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
python manage.py migrate
```

Export values from `.env` in your shell when overriding the development
defaults.

## Run

```bash
python manage.py runserver
```

Check process health:

```bash
curl http://127.0.0.1:8000/health/
```

Expected response:

```json
{"status": "ok"}
```

## Test

```bash
ruff check .
ruff format --check .
pytest
python manage.py check
```
