"""URL configuration for the fuel route optimizer."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from config.views import health, route_planner_demo

urlpatterns = [
    path("", route_planner_demo, name="route-planner-demo"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include("routing.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]
