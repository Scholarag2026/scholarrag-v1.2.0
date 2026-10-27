"""The release version is one number across every place that states it."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_VERSION = "1.2.0"


def test_backend_pyproject_states_the_release_version():
    data = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == RELEASE_VERSION


def test_fastapi_app_states_the_release_version():
    source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    match = re.search(r'FastAPI\(title="ScholarRAG API", version="([^"]+)"', source)
    assert match is not None
    assert match.group(1) == RELEASE_VERSION


def test_frontend_package_states_the_release_version():
    for name in ("package.json", "package-lock.json"):
        data = json.loads((ROOT / "frontend" / name).read_text(encoding="utf-8"))
        assert data["version"] == RELEASE_VERSION, name
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""]["version"] == RELEASE_VERSION


def test_demo_runner_and_protocol_state_the_release_version():
    runner = (ROOT / "demo" / "run_demo.py").read_text(encoding="utf-8")
    match = re.search(r'^SUMMARY_VERSION = "([^"]+)"', runner, re.MULTILINE)
    assert match is not None
    assert match.group(1) == RELEASE_VERSION
    assert f"ScholarRAG v{RELEASE_VERSION}" in runner.split('"""', 2)[1]
    protocol = json.loads((ROOT / "demo" / "protocol.json").read_text(encoding="utf-8"))
    assert f"ScholarRAG v{RELEASE_VERSION}" in protocol["notes"]
