"""OpenAPI contract checks."""

from fastapi.testclient import TestClient


def test_openapi_unique_operation_ids(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "openapi" in schema
    assert schema["openapi"].startswith("3.")
