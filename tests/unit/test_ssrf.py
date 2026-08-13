import pytest
from app.core.errors import InvalidSourceURL
from app.storage.ssrf import validate_public_https_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.mp3",
        "https://localhost/a.mp3",
        "https://127.0.0.1/a.mp3",
        "https://10.0.0.1/a.mp3",
        "https://192.168.1.1/a.mp3",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/a.mp3",
    ],
)
def test_ssrf_rejects_private_and_non_https(url: str) -> None:
    with pytest.raises(InvalidSourceURL):
        validate_public_https_url(url)
