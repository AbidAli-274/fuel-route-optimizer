from importlib import import_module

from django.apps import AppConfig


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "routing"

    def ready(self) -> None:
        import_module("routing.checks")
