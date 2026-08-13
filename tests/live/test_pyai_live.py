"""Live PyAI tests. Never run in normal CI."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.mark.skipif(os.environ.get("RUN_PYAI_LIVE_TESTS") != "1", reason="live PyAI tests disabled")
def test_pyai_live_submit_not_run_by_default() -> None:
    assert os.environ.get("PYAI_API_KEY"), "PYAI_API_KEY is required for live tests"
