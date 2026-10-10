import os

import pytest

from app.main import setup_provider
from app.config.settings import load_settings


def test_setup_writes_private_credentials(tmp_path):
    answers = iter(["openai", "", "gpt-test"])
    path = setup_provider(tmp_path, input_fn=lambda _: next(answers), secret_fn=lambda _: "sk-test-secret")
    assert path.stat().st_mode & 0o777 == 0o600
    settings = load_settings(tmp_path)
    assert settings.provider == "openai"
    assert settings.model == "gpt-test"
    assert settings.api_key.get_secret_value() == "sk-test-secret"


def test_setup_rejects_bad_provider_without_secret_prompt(tmp_path):
    with pytest.raises(ValueError, match="服务商"):
        setup_provider(tmp_path, input_fn=lambda _: "unknown", secret_fn=lambda _: pytest.fail("secret prompt"))
    assert not (tmp_path / ".env").exists()


def test_setup_rejects_insecure_base_url(tmp_path):
    answers = iter(["doubao", "http://example.test/v1"])
    with pytest.raises(ValueError, match="HTTPS"):
        setup_provider(tmp_path, input_fn=lambda _: next(answers), secret_fn=lambda _: pytest.fail("secret prompt"))
    assert not (tmp_path / ".env").exists()


def test_setup_refuses_overwrite(tmp_path):
    path = tmp_path / ".env"
    path.write_text("JARVIS_PROVIDER=mock\n")
    with pytest.raises(FileExistsError):
        setup_provider(tmp_path, input_fn=lambda _: pytest.fail("prompt"))
    assert path.read_text() == "JARVIS_PROVIDER=mock\n"
