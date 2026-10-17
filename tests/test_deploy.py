"""Deployment configs stay consistent with the app: env var names, $PORT, packaging, bundles."""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "omniknow"
COMPOSE_ONLY = {"OMNIKNOW_HOST_PORT"}


def _known_env_vars() -> set[str]:
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        names |= set(re.findall(r'"(OMNIKNOW_[A-Z_]+)"', path.read_text(encoding="utf-8")))
    return names


def _documented_env_vars() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^(OMNIKNOW_[A-Z_]+)=", text, flags=re.MULTILINE))


def test_env_example_documents_exactly_the_vars_the_code_reads() -> None:
    known = _known_env_vars()
    assert {
        "OMNIKNOW_PROVIDER",
        "OMNIKNOW_API_KEYS",
        "OMNIKNOW_DEV_MODE",
        "OMNIKNOW_TRUST_PROXY",
        "OMNIKNOW_ASK_LIMIT_PER_MINUTE",
        "OMNIKNOW_CORPUS_DIR",
    } <= known
    assert known == _documented_env_vars() - COMPOSE_ONLY


def test_render_blueprint() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "runtime: docker" in text and "healthCheckPath: /healthz" in text
    keys = set(re.findall(r"- key: (\S+)", text))
    assert keys and keys <= _known_env_vars()
    assert "OMNIKNOW_API_KEY\n" not in text


def test_fly_config_matches_port_and_health_check() -> None:
    fly = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))
    assert fly["build"]["dockerfile"] == "Dockerfile"
    assert int(fly["env"]["PORT"]) == fly["http_service"]["internal_port"]
    assert set(fly["env"]) - {"PORT"} <= _known_env_vars()
    assert fly["http_service"]["checks"][0]["path"] == "/healthz"


def test_railway_config() -> None:
    railway = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert railway["build"]["builder"] == "DOCKERFILE"
    assert railway["deploy"]["healthcheckPath"] == "/healthz"


def test_dockerfile_is_non_root_and_honours_port() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:${PYTHON_VERSION}-slim AS build" in text and "AS runtime" in text
    assert "--uid 10001" in text and "USER omniknow" in text
    assert "HEALTHCHECK" in text and "/healthz" in text
    assert "${PORT:-8000}" in text and "omniknow serve --host 0.0.0.0" in text


def test_compose_is_hardened() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for needle in (
        "read_only: true",
        "/tmp:rw,nosuid,nodev",
        "- ALL",
        "no-new-privileges:true",
        "pids_limit:",
        "mem_limit:",
        "cpus:",
    ):
        assert needle in text, needle


def test_dockerignore_keeps_secrets_out() -> None:
    lines = set((ROOT / ".dockerignore").read_text(encoding="utf-8").split())
    assert {".env", ".git", ".venv", "tests"} <= lines


def test_wheel_ships_corpus_without_duplicate_force_include() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/omniknow"]
    # The package dir already carries data/ and api/static/; force-including them again
    # produces duplicate zip entries that break `pip wheel`.
    assert "force-include" not in wheel
    deps = " ".join(pyproject["project"]["dependencies"])
    assert "fastapi" in deps and "uvicorn" in deps
    manifest = json.loads((SRC / "data" / "corpus" / "manifest.json").read_text("utf-8"))
    for doc in manifest["documents"]:
        assert (SRC / "data" / "corpus" / doc["path"]).is_file(), doc["path"]
    assert (SRC / "data" / "corpus" / "products" / "x200-datasheet.pdf").is_file()
    assert (SRC / "data" / "corpus" / "facilities" / "office-floorplan.png").is_file()


def test_requirements_match_runtime_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    reqs = {
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert reqs == set(pyproject["project"]["dependencies"])


def test_vercel_bundles_package_data_and_routes_everything_to_the_app() -> None:
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    function = vercel["functions"]["api/index.py"]
    assert function["includeFiles"] == "src/omniknow/**"
    assert {"source": "/(.*)", "destination": "/api/index"} in vercel["rewrites"]
    assert (SRC / "api" / "static" / "index.html").is_file()


def test_serverless_entrypoint_is_a_public_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OMNIKNOW_API_KEYS", "OMNIKNOW_DEV_MODE", "OMNIKNOW_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        cfg = client.get("/api/config").json()
        assert cfg["access_mode"] == "public-demo" and cfg["simulated"] is True
        assert "OmniKnow" in client.get("/").text
        res = client.post(
            "/api/ask",
            json={"question": "What is the X200 payload capacity?", "principal": "guest"},
        )
        assert res.status_code == 200
        assert "12 kg" in res.json()["answer"]["answer"]


def test_ci_runs_docker_smoke_job() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "docker compose up --build" in text
    assert "scripts/smoke_test.py" in text
