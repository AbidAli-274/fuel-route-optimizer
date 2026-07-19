"""Smoke tests for the project bootstrap."""

from django.conf import settings
from django.contrib import admin
from django.test import Client

from fuel.models import FuelStation
from routing.models import GeocodeCache, RouteCache


def test_health_endpoint_does_not_require_database(client: Client) -> None:
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_route_planner_demo_renders_without_database(client: Client) -> None:
    response = client.get("/")
    content = response.content.decode()

    assert response.status_code == 200
    assert "Fuel Route Optimizer" in content
    assert 'data-api-url="/api/v1/route-plans/"' in content
    assert "leaflet@1.9.4" in content


def test_bootstrap_configuration() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert "rest_framework" in settings.INSTALLED_APPS
    assert "fuel.apps.FuelConfig" in settings.INSTALLED_APPS


def test_project_models_are_registered_in_admin() -> None:
    assert FuelStation in admin.site._registry
    assert GeocodeCache in admin.site._registry
    assert RouteCache in admin.site._registry
