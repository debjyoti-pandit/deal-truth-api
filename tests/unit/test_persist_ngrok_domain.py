from scripts.persist_ngrok_domain import hostname_from_public_url, persist_ngrok_domain


def test_hostname_from_public_url() -> None:
    assert hostname_from_public_url("https://stable.ngrok-free.app") == "stable.ngrok-free.app"
    assert hostname_from_public_url("stable.ngrok-free.app") == "stable.ngrok-free.app"
    assert hostname_from_public_url("http://localhost:8000") is None


def test_persist_writes_empty_domain() -> None:
    text, host, wrote = persist_ngrok_domain("NGROK_DOMAIN=\n", "https://stable.ngrok-free.app")
    assert wrote is True
    assert host == "stable.ngrok-free.app"
    assert "NGROK_DOMAIN=stable.ngrok-free.app" in text


def test_persist_keeps_existing_domain() -> None:
    text, host, wrote = persist_ngrok_domain(
        "NGROK_DOMAIN=stable.ngrok-free.app\n",
        "https://other.ngrok-free.app",
    )
    assert wrote is False
    assert host == "stable.ngrok-free.app"
    assert "NGROK_DOMAIN=stable.ngrok-free.app" in text
