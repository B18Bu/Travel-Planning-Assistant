from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from app.config import Settings


ENV_EXAMPLE = Path(__file__).parents[1] / ".env.example"


def test_flyai_ticket_settings_have_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.fliggy_ticket_provider == "disabled"
    assert settings.flyai_api_key == ""
    assert settings.flyai_timeout_seconds == 30


@pytest.mark.parametrize("provider", ["disabled", "mock", "flyai"])
def test_flyai_ticket_settings_accept_supported_providers(provider: Literal["disabled", "mock", "flyai"]):
    settings = Settings(_env_file=None, fliggy_ticket_provider=provider)

    assert settings.fliggy_ticket_provider == provider


def test_flyai_ticket_settings_reject_unsupported_provider():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, fliggy_ticket_provider="top")


@pytest.mark.parametrize("timeout", [0, 121, -1, "0", "121"])
def test_flyai_ticket_settings_reject_timeout_outside_one_to_120(timeout):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, flyai_timeout_seconds=timeout)


def test_env_example_documents_flyai_ticket_settings_without_real_key():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "FLIGGY_TICKET_PROVIDER=disabled" in text
    assert "FLYAI_API_KEY=" in text
    assert "FLYAI_TIMEOUT_SECONDS=30" in text
