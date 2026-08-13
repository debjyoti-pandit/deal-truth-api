from app.core.settings import Settings


def test_cors_includes_ngrok_https_origin() -> None:
    settings = Settings(
        cors_origins="http://localhost:5173",
        ngrok_domain="deal-truth-ngrok.ngrok-free.app",
    )
    assert "http://localhost:5173" in settings.cors_origin_list
    assert "https://deal-truth-ngrok.ngrok-free.app" in settings.cors_origin_list
