from fastapi.testclient import TestClient


def test_reference_lists_architecture(client: TestClient) -> None:
    response = client.get("/api/v1/reference")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["docs"]}
    assert "ARCHITECTURE.md" in names
    assert "evidence.md" in names
    assert "providers.md" in names
    assert "search.md" in names


def test_reference_serves_architecture_markdown(client: TestClient) -> None:
    response = client.get("/api/v1/reference/ARCHITECTURE.md")
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "NO PROOF IN THE TRANSCRIPT" in response.text


def test_reference_rejects_path_traversal(client: TestClient) -> None:
    response = client.get("/api/v1/reference/../.env")
    assert response.status_code == 404
