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

The project automatically loads `.env` from the repository root with
`python-dotenv`. Exported shell variables take precedence over values in the
file.

Create a free OpenRouteService account and API key at
[openrouteservice.org](https://openrouteservice.org/dev/#/signup), then set it
in `.env`:

```dotenv
DJANGO_SECRET_KEY=replace-with-a-local-secret
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_DB_PATH=db.sqlite3
OPENROUTESERVICE_API_KEY=replace-with-your-openrouteservice-key
ORS_BASE_URL=https://api.openrouteservice.org
ROUTING_CONNECT_TIMEOUT_SECONDS=3
ROUTING_READ_TIMEOUT_SECONDS=15
GEOCODE_CACHE_TTL_SECONDS=2592000
ROUTE_CACHE_TTL_SECONDS=604800
STATION_CORRIDOR_MILES=10
```

`OPENROUTESERVICE_API_KEY` is required. Django's startup check reports
`routing.E001` when it is missing or still contains a known placeholder.

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

## Docker

Docker Compose mounts the project for development and stores SQLite data in a
named volume.

```bash
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py import_fuel_prices
```

The application is available at `http://127.0.0.1:8000/`. The Dockerfile uses
Gunicorn by default; Compose overrides it with Django's development server for
automatic code reload.

## Test

```bash
ruff check .
ruff format --check .
pytest
python manage.py check
```
