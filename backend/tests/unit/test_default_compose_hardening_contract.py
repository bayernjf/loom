"""Q200 #33 contract guard: default compose hardening (Q199 #33).

Three defects registered by the MVP re-review:
- the base compose published 5432/6379/9000-9001 on the host,
- datastore credentials were hard-coded literals,
- an empty LOOM_MASTER_KEY only produced a runtime warning (encrypted outbound
  keys would silently become undecryptable after a restart).

These tests parse the artifacts statically (no Docker daemon), mirroring the
style of test_deployment_artifacts_contract.py.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
BACKEND_ENTRYPOINT = REPO_ROOT / "backend" / "docker-entrypoint.sh"
REHEARSAL_SCRIPTS = (
    REPO_ROOT / "infra" / "ha-rehearsal.sh",
    REPO_ROOT / "infra" / "load-rehearsal.sh",
    REPO_ROOT / "infra" / "alerting-rehearsal.sh",
)
INFRA_SERVICES = ("postgres", "redis", "minio")


def test_base_compose_infra_ports_are_loopback_only() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    for name in INFRA_SERVICES:
        ports = services[name]["ports"]
        assert ports, f"{name} must keep host access for local ops"
        for entry in ports:
            assert entry.startswith("127.0.0.1:"), (
                f"{name} publishes {entry} off loopback; Q200 #33 requires "
                "loopback-only datastore exposure"
            )
    # The app services still follow Q144: only the frontend publishes a host port.
    assert "ports" not in services["backend"]


def test_base_compose_credentials_are_env_interpolated() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    pg_env = services["postgres"]["environment"]
    assert "${POSTGRES_PASSWORD:-" in pg_env["POSTGRES_PASSWORD"]
    assert pg_env["POSTGRES_PASSWORD"] != "loom"
    minio_env = services["minio"]["environment"]
    assert "${MINIO_ROOT_PASSWORD:-" in minio_env["MINIO_ROOT_PASSWORD"]
    assert minio_env["MINIO_ROOT_PASSWORD"] != "minioadmin"
    # The backend DSN and helpers must consume the same interpolated values.
    dsn = services["backend"]["environment"]["LOOM_DATABASE_DSN"]
    assert "${POSTGRES_USER:-" in dsn and "${POSTGRES_PASSWORD:-" in dsn
    assert services["db-backup"]["environment"]["PGPASSWORD"].startswith("${")
    assert services["db-basebackup"]["environment"]["PGPASSWORD"].startswith("${")
    wal = services["wal-archiver"]["environment"]
    assert wal["S3_ACCESS_KEY"].startswith("${")
    assert wal["S3_SECRET_KEY"].startswith("${")


def test_backend_entrypoint_fails_fast_on_empty_master_key() -> None:
    content = BACKEND_ENTRYPOINT.read_text()
    # The check must exist and run before migrations/serving (fail-fast at boot,
    # not lazily on first decrypt).
    assert "LOOM_MASTER_KEY" in content
    assert "exit 1" in content
    assert content.index("LOOM_MASTER_KEY") < content.index("alembic upgrade head")
    assert content.index("LOOM_MASTER_KEY") < content.index("exec uvicorn app.main:app")


def test_base_compose_datastores_restart_policy() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    for name in INFRA_SERVICES:
        assert services[name].get("restart") == "unless-stopped", (
            f"{name} must self-heal after a host reboot; Q199 #33 required "
            "restart for all three datastores"
        )


def test_rehearsal_scripts_keep_entrypoint_fail_fast_satisfiable() -> None:
    # The entrypoint now rejects empty master keys; rehearsal stacks (synthetic,
    # no real provider keys) must inject a rehearsal-only value or they break.
    for path in REHEARSAL_SCRIPTS:
        content = path.read_text()
        assert "export LOOM_MASTER_KEY" in content, path.name
        assert "loom-rehearsal-only-master-key" in content, path.name
        assert "${LOOM_MASTER_KEY:-" in content, path.name
