from scripts.check_endpoints import fill_path, probes_from_openapi, run_in_process


def test_fill_path_uses_uuid_placeholders() -> None:
    filled = fill_path("/api/v1/calls/{call_id}/report")
    assert "{call_id}" not in filled
    assert "00000000-0000-4000-8000-000000000001" in filled


def test_probes_include_health_and_skip_stream() -> None:
    schema = {
        "paths": {
            "/health/live": {"get": {}},
            "/api/v1/calls/{call_id}/stream": {"get": {}},
            "/api/v1/calls": {"get": {}, "post": {}},
        }
    }
    probes = probes_from_openapi(schema)
    paths = {(p.method, p.path) for p in probes}
    assert ("GET", "/health/live") in paths
    assert ("GET", "/api/v1/calls") in paths
    assert not any("/stream" in path for _, path in paths)


def test_in_process_smoke_has_no_failures() -> None:
    results = run_in_process()
    failed = [item for item in results if not item.passed]
    assert results
    assert failed == []
