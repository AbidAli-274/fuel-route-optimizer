import os
from pathlib import Path

from django.conf import settings
from django.core.checks import run_checks
from django.test import override_settings

from config.environment import load_environment


def test_environment_template_uses_runtime_api_key_name() -> None:
    template = (settings.BASE_DIR / ".env.example").read_text(encoding="utf-8")

    assert "OPENROUTESERVICE_API_KEY=" in template
    assert "\nORS_API_KEY=" not in template


def test_local_dotenv_file_is_loaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "OPENROUTESERVICE_API_KEY=loaded-from-dotenv\n",
        encoding="utf-8",
    )

    load_environment(tmp_path)

    assert os.environ["OPENROUTESERVICE_API_KEY"] == "loaded-from-dotenv"


def test_exported_environment_takes_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "exported-value")
    (tmp_path / ".env").write_text(
        "OPENROUTESERVICE_API_KEY=dotenv-value\n",
        encoding="utf-8",
    )

    load_environment(tmp_path)

    assert os.environ["OPENROUTESERVICE_API_KEY"] == "exported-value"


@override_settings(ORS_API_KEY="")
def test_system_check_reports_missing_api_key() -> None:
    errors = run_checks()

    assert any(error.id == "routing.E001" for error in errors)


@override_settings(ORS_API_KEY="configured-key")
def test_system_check_accepts_configured_api_key() -> None:
    errors = run_checks()

    assert not any(error.id == "routing.E001" for error in errors)


@override_settings(ORS_API_KEY="replace-with-your-openrouteservice-key")
def test_system_check_rejects_documented_placeholder() -> None:
    errors = run_checks()

    assert any(error.id == "routing.E001" for error in errors)
