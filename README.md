# Fuel Route Optimizer

A Django application that calculates a driving route between two locations in
the contiguous United States, identifies cost-effective fuel stops, and
estimates fuel purchased during the trip. It includes a documented REST API and
a small Leaflet map for demonstrating the result.

The solution is intentionally scoped as a polished take-home assessment:
SQLite keeps setup small, OpenRouteService provides geocoding and routing, and
the optimization policy is deterministic and explainable.

## Features

- Route planning for U.S. start and finish locations
- Responsive Leaflet demo with OpenStreetMap tiles
- GeoJSON route geometry suitable for rendering on a map
- Fuel-stop selection from the supplied assessment price data
- A 500-mile vehicle range and 10 MPG fuel-consumption model
- Optional inclusion of the starting tank's purchase cost
- Persistent geocode and route caches that reduce provider calls
- Idempotent fuel-price import with median duplicate pricing
- OpenAPI schema, Swagger UI, and ReDoc
- Docker and local development workflows
- Structured, documented API errors

## Architecture

The code is separated into two Django applications and the project
configuration:

- `fuel` owns the normalized `FuelStation` model, CSV/GeoNames import, and
  route-corridor station selection.
- `routing` owns the OpenRouteService client, persistent caches, route
  orchestration, fuel optimization, serializers, and API view.
- `config` owns environment loading, Django settings, health checks, URLs,
  OpenAPI configuration, and the demo template.

A route request flows through these layers:

1. The API validates the request.
2. The routing service resolves both locations and retrieves a driving route,
   consulting SQLite caches first.
3. Fuel stations are projected onto the route and filtered to the configured
   corridor.
4. The optimizer selects purchases that satisfy the vehicle range.
5. The response serializer returns route geometry, stops, costs, assumptions,
   attribution, and warnings.

## Technology stack

- Python 3.12+
- Django 6.0.7
- Django REST Framework
- drf-spectacular
- OpenRouteService and OpenStreetMap
- SQLite
- GeoNames U.S. postal-code data
- httpx
- python-dotenv
- Gunicorn
- Docker Compose
- pytest, pytest-django, and Ruff

## Assumptions

- Both locations must resolve within the contiguous United States.
- The vehicle starts with a full 50-gallon tank.
- Fuel economy is fixed at 10 miles per gallon, giving a 500-mile range.
- The destination fuel reserve is zero gallons.
- Starting fuel is treated as already owned by default. Set
  `include_initial_fill` to include the cost of buying that full tank.
- Fuel prices remain decimal values with eight fractional digits internally;
  monetary response values are rounded to cents.
- Station access detours are excluded from route distance, duration, and fuel
  use.
- GeoNames city centroids approximate station locations because the source CSV
  has no coordinates.

## Fuel optimization

Stations within the configured route corridor are ordered by their projected
route mile. At each station, the greedy policy:

1. Looks for the first cheaper station reachable with one tank.
2. Buys only enough fuel to reach that cheaper station or the destination.
3. If neither is reachable, fills to tank capacity.
4. Reports an infeasible-plan error when a required gap exceeds 500 miles.

For a fixed route with ordered stations, no detour cost, constant fuel economy,
and no destination reserve, buying only enough to reach a cheaper option—and
otherwise buying as much as needed—is cost-effective and avoids the complexity
of a graph or dynamic-programming solution.

`total_fuel_cost` equals en-route purchases by default. When
`include_initial_fill` is true, the supplied starting price is applied to all
50 starting gallons and added to the total.

## Caching and provider calls

Geocodes are cached for 30 days by normalized input query. Routes are cached
for 7 days by provider, profile, and resolved endpoint coordinates. Both
caches are stored in SQLite and survive process restarts.

A cold request normally makes three OpenRouteService calls: two geocodes and
one directions request. A fully cached request makes none. A stale route with
fresh geocodes makes one directions request. Transient transport errors and
provider 502/503/504 responses are retried once.

## Environment configuration

Copy the template before running any Django command:

```bash
cp .env.example .env
```

Create a free OpenRouteService account and key at
[openrouteservice.org](https://openrouteservice.org/dev/#/signup), then edit
`.env`:

```dotenv
DJANGO_SECRET_KEY=replace-with-a-long-random-local-secret
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

Configuration values:

- `DJANGO_SECRET_KEY`: Django cryptographic signing key. Use a unique,
  unpredictable value outside local development.
- `DJANGO_DEBUG`: accepts `1`, `true`, `yes`, or `on` as true.
- `DJANGO_ALLOWED_HOSTS`: comma-separated host names.
- `DJANGO_DB_PATH`: SQLite file path.
- `OPENROUTESERVICE_API_KEY`: required OpenRouteService key.
- `ORS_BASE_URL`: provider base URL.
- `ROUTING_CONNECT_TIMEOUT_SECONDS`: provider connection timeout.
- `ROUTING_READ_TIMEOUT_SECONDS`: provider response timeout.
- `GEOCODE_CACHE_TTL_SECONDS`: geocode cache lifetime; default 30 days.
- `ROUTE_CACHE_TTL_SECONDS`: route cache lifetime; default 7 days.
- `STATION_CORRIDOR_MILES`: maximum station distance from the route.

The repository-root `.env` is loaded with `python-dotenv`. Exported process
variables take precedence. `.env` and its local variants are ignored by Git
and Docker. Django reports `routing.E001` if the routing key is absent or is a
known placeholder; no API keys are stored in source code.

## Docker quick start

Prerequisites: Docker Engine or Docker Desktop with Compose v2.

```bash
cp .env.example .env
# Edit .env and set DJANGO_SECRET_KEY and OPENROUTESERVICE_API_KEY.
docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py import_fuel_prices
docker compose exec web python manage.py check
```

Then open the map demo at `http://127.0.0.1:8000/` or Swagger at
`http://127.0.0.1:8000/api/docs/`. The first import downloads and caches the
GeoNames U.S. archive; subsequent imports reuse it. Compose mounts the source
tree for development and stores SQLite at `/data/db.sqlite3` in the
`sqlite_data` named volume.

Useful lifecycle commands:

```bash
docker compose logs -f web
docker compose down
docker compose down --volumes  # Also deletes the persisted SQLite database.
```

The image uses a non-root user, a health check, and Gunicorn by default.
Compose overrides Gunicorn with Django's auto-reloading development server.

## Local development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
# Edit .env and set DJANGO_SECRET_KEY and OPENROUTESERVICE_API_KEY.
python manage.py migrate
python manage.py import_fuel_prices
python manage.py runserver
```

Verify the process:

```bash
curl http://127.0.0.1:8000/health/
```

Expected response:

```json
{"status":"ok"}
```

## Fuel-price import

The default command imports `fuel-prices-for-be-assessment.csv`:

```bash
python manage.py import_fuel_prices
```

The importer keeps U.S. rows, normalizes whitespace and state casing, verifies
that repeated OPIS IDs represent the same physical station, and stores the
median price and source-row count. Coordinates are matched by normalized
city/state against the GeoNames U.S. postal-code dataset. Re-running the same
input is idempotent.

Custom inputs are supported:

```bash
python manage.py import_fuel_prices \
  --csv /path/to/prices.csv \
  --geonames-zip /path/to/US.zip
```

Partial imports do not delete existing stations. Use `--replace` explicitly
when the supplied CSV is intended to be the complete source of truth:

```bash
python manage.py import_fuel_prices --replace
```

The command prints source, filtered, duplicate, coordinate-match, create,
update, unchanged, and delete counts.

## Demo frontend

Open `http://127.0.0.1:8000/` after starting the application.

The page uses a Django template, vanilla JavaScript, Leaflet 1.9.4, and
OpenStreetMap tiles. It calls the existing route-planning API, draws the
returned GeoJSON route, adds start/finish and fuel-stop markers, and displays
the trip summary. Marker popups show the station address, route mile, price,
gallons purchased, and purchase cost.

The frontend contains presentation logic only. Route selection, station
selection, gallons, and costs are calculated by the backend. Leaflet is loaded
from the pinned unpkg CDN release, so the browser needs internet access for the
map library and OpenStreetMap tiles.

## API documentation

With the server running:

- Demo map: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/api/docs/`
- ReDoc: `http://127.0.0.1:8000/api/redoc/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`
- Health check: `http://127.0.0.1:8000/health/`

Swagger is the recommended demonstration interface and can execute requests
without Postman. The API is public for assessment purposes and has no
application-level authentication.

## Route-planning API

`POST /api/v1/route-plans/`

Minimal request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/route-plans/ \
  -H "Content-Type: application/json" \
  -d '{
    "start": "Dallas, TX",
    "finish": "Albuquerque, NM"
  }'
```

To include the starting tank:

```json
{
  "start": "Dallas, TX",
  "finish": "Albuquerque, NM",
  "include_initial_fill": true,
  "initial_fuel_price_per_gallon": "3.25000000"
}
```

Example response (route values depend on current provider data):

```json
{
  "start": {
    "input": "Dallas, TX",
    "resolved_name": "Dallas, Texas, United States",
    "latitude": 32.7767,
    "longitude": -96.797
  },
  "finish": {
    "input": "Albuquerque, NM",
    "resolved_name": "Albuquerque, New Mexico, United States",
    "latitude": 35.0844,
    "longitude": -106.6504
  },
  "route": {
    "distance_miles": 646.23,
    "duration_minutes": 590.0,
    "geometry": {
      "type": "LineString",
      "coordinates": [
        [-96.797, 32.7767],
        [-106.6504, 35.0844]
      ]
    }
  },
  "fuel_stops": [
    {
      "sequence": 1,
      "station_id": 123,
      "name": "Example Travel Center",
      "address": "I-40 Exit 75",
      "city": "Amarillo",
      "state": "TX",
      "location": {
        "latitude": 35.22,
        "longitude": -101.83,
        "accuracy": "city_centroid"
      },
      "route_mile": 362.1,
      "distance_from_route_miles": 2.4,
      "price_per_gallon": "3.12900000",
      "arrival_fuel_gallons": 13.79,
      "gallons_purchased": 14.83,
      "departure_fuel_gallons": 28.62,
      "purchase_cost": "46.40"
    }
  ],
  "cost_summary": {
    "currency": "USD",
    "estimated_fuel_consumed_gallons": 64.62,
    "en_route_gallons_purchased": 14.83,
    "en_route_fuel_cost": "46.40",
    "initial_fill_included": false,
    "initial_fill_gallons": 0.0,
    "initial_fill_price_per_gallon": null,
    "initial_fill_cost": "0.00",
    "total_fuel_cost": "46.40",
    "final_fuel_gallons": 0.21
  },
  "assumptions": {
    "fuel_efficiency_mpg": 10.0,
    "tank_capacity_gallons": 50.0,
    "maximum_range_miles": 500.0,
    "starting_tank": "full",
    "destination_reserve_gallons": 0.0,
    "station_detours_included": false
  },
  "metadata": {
    "routing_provider": "openrouteservice",
    "routing_profile": "driving-car",
    "route_cache_hit": false,
    "fuel_price_source": "fuel-prices-for-be-assessment.csv",
    "station_coordinate_source": "GeoNames",
    "price_duplicate_policy": "median",
    "attribution": [
      "Routing and geocoding: openrouteservice.org by HeiGIT",
      "Map data: OpenStreetMap contributors",
      "Station coordinates: GeoNames, CC BY 4.0"
    ]
  },
  "warnings": [
    "Fuel-station coordinates are city centroids and may not represent exact driveway locations.",
    "Station access detours are excluded from route distance and fuel calculations."
  ]
}
```

## Error responses

Application errors use this envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request is invalid.",
    "details": {
      "finish": ["Start and finish must be different locations."]
    }
  }
}
```

Documented route-planning errors:

- `400 VALIDATION_ERROR`: invalid fields or malformed JSON.
- `400 LOCATION_NOT_FOUND`: a location cannot be resolved in the supported
  area.
- `422 NO_FEASIBLE_FUEL_PLAN`: no station sequence satisfies the 500-mile
  range; details identify the failing route gap.
- `429 ROUTING_RATE_LIMITED`: provider quota or rate limit; `Retry-After` is
  forwarded when available.
- `502 ROUTING_UNAVAILABLE`: provider, transport, or response-validation
  failure.
- `503 ROUTING_NOT_CONFIGURED`: missing, placeholder, or provider-rejected
  routing API key.

## Validation and tests

Run the final submission checks:

```bash
ruff check .
ruff format --check .
pytest
python manage.py check
python manage.py migrate --check
python manage.py spectacular --file /tmp/openapi.yml --validate
docker compose config --quiet
```

Tests cover data normalization and import safety, model validation, caching,
provider retries and failures, route response validation, station projection,
fuel optimization, API success/error behavior, environment loading, and
OpenAPI availability.

## Security notes

- Secrets and API keys belong only in ignored `.env` files or process
  environment variables.
- The committed template contains no credential.
- The container runs as a non-root user and excludes local environment files
  from its build context.
- Set `DJANGO_DEBUG=false`, use a strong `DJANGO_SECRET_KEY`, configure the
  deployment host list, and terminate TLS at the deployment platform for any
  non-local environment.
- This assessment API does not implement authentication, request throttling,
  or user-level quotas.

## Limitations

- Station locations are city centroids, not exact pumps or highway exits.
- Detour distance, station access, taxes, price changes, traffic, and vehicle
  load are not modeled.
- The station corridor uses geometric proximity to route segments rather than
  road-network detour time.
- SQLite is appropriate for this single-service assessment but is not intended
  for high write concurrency or horizontal scaling.
- Availability and route quality depend on OpenRouteService and its free-tier
  quota.
- Coverage is limited by the supplied fuel-price dataset and contiguous-U.S.
  routing scope.

## Future improvements

- Import exact station coordinates from a verified commercial or government
  source.
- Include road-network detour time and fuel cost in station selection.
- Add request throttling, authentication, observability, and provider circuit
  breaking.
- Move to PostgreSQL for concurrent production workloads.
- Refresh fuel prices through a scheduled, versioned ingestion pipeline.
- Self-host static frontend dependencies for fully controlled deployments.
