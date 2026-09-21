"""Contract guard for the minimum deployment artifacts (Q144 checklist #4).

The private beta runs from docker-compose on a single host. These tests parse
the artifacts statically (no Docker daemon) to keep the deployment invariants
explicit: the backend image migrates before serving, the frontend runs the
standalone build, and the backend is never published off the compose network.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
BACKEND_ENTRYPOINT = REPO_ROOT / "backend" / "docker-entrypoint.sh"
FRONTEND_DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile"
NEXT_CONFIG = REPO_ROOT / "frontend" / "next.config.mjs"
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"


def test_backend_image_installs_app_and_serves_with_healthcheck() -> None:
    content = BACKEND_DOCKERFILE.read_text()
    assert "pip install ." in content
    assert "/healthz" in content
    assert 'ENTRYPOINT ["docker-entrypoint.sh"]' in content


def test_backend_entrypoint_migrates_before_serving() -> None:
    content = BACKEND_ENTRYPOINT.read_text()
    assert "set -e" in content
    assert "alembic upgrade head" in content
    assert content.index("alembic upgrade head") < content.index(
        "exec uvicorn app.main:app"
    )


def test_frontend_image_builds_and_runs_standalone() -> None:
    content = FRONTEND_DOCKERFILE.read_text()
    assert content.count("FROM node") >= 3
    assert "npm ci" in content
    assert "npm run build" in content
    assert "/app/.next/standalone" in content
    assert 'CMD ["node", "server.js"]' in content
    assert 'ENV HOSTNAME=0.0.0.0' in content


def test_next_config_emits_standalone_output() -> None:
    assert 'output: "standalone"' in NEXT_CONFIG.read_text()


def test_compose_runs_app_services_with_backend_unpublished() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    assert {"backend", "frontend"} <= set(services)

    backend = services["backend"]
    assert "ports" not in backend
    assert "8000" in str(backend.get("expose"))

    backend_env = backend["environment"]
    assert "@postgres:5432/" in backend_env["LOOM_DATABASE_DSN"]
    assert "//redis:6379" in backend_env["LOOM_REDIS_DSN"]
    assert backend["depends_on"]["postgres"]["condition"] == "service_healthy"

    frontend = services["frontend"]
    assert "3000:3000" in frontend["ports"]
    assert frontend["environment"]["LOOM_API_BASE_URL"] == "http://backend:8000"
    assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
