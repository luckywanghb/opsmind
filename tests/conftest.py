"""Repository-wide test isolation for local persistence."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_run_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent any API test from writing the developer's default database."""

    monkeypatch.setenv("OPSMIND_RUN_STORE_PATH", str(tmp_path / "opsmind.db"))
