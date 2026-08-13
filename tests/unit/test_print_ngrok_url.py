from __future__ import annotations

from scripts.print_ngrok_url import fetch_https_url, pinned_domain_url


def test_fetch_https_url_treats_connection_reset_as_not_ready(monkeypatch) -> None:
    def _reset(request: object, timeout: float = 0):
        raise ConnectionResetError(54, "Connection reset by peer")

    monkeypatch.setattr("scripts.print_ngrok_url.urllib.request.urlopen", _reset)
    assert fetch_https_url("http://127.0.0.1:4040") is None


def test_fetch_https_url_parses_https_tunnel(monkeypatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"tunnels":[{"public_url":"https://abc.ngrok-free.app"}]}'

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("scripts.print_ngrok_url.urllib.request.urlopen", lambda *a, **k: _Resp())
    assert fetch_https_url("http://127.0.0.1:4040") == "https://abc.ngrok-free.app"


def test_pinned_domain_url_from_env(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NGROK_DOMAIN=deal-truth-ngrok.ngrok-free.app\n", encoding="utf-8")
    assert pinned_domain_url(env_file) == "https://deal-truth-ngrok.ngrok-free.app"
