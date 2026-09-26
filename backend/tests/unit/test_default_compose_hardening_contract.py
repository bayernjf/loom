"""Q200 #33 contract guard: default compose hardening (Q199 #33).

Three defects registered by the MVP re-review:
- the base compose published 5432/6379/9000-9001 on the host,
- datastore credentials were hard-coded literals,
- an empty LOOM_MASTER_KEY only produced a runtime warning (encrypted outbound
  keys would silently become undecryptable after a restart).

These tests parse the artifacts statically (no Docker daemon), mirroring the
style of test_deployment_artifacts_contract.py.
"""

import re
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
    assert "${POSTGRES_PASSWORD" in pg_env["POSTGRES_PASSWORD"]
    assert pg_env["POSTGRES_PASSWORD"] != "loom"
    minio_env = services["minio"]["environment"]
    assert "${MINIO_ROOT_PASSWORD" in minio_env["MINIO_ROOT_PASSWORD"]
    assert minio_env["MINIO_ROOT_PASSWORD"] != "minioadmin"
    # The backend DSN and helpers must consume the same interpolated values.
    dsn = services["backend"]["environment"]["LOOM_DATABASE_DSN"]
    assert "${POSTGRES_USER:-" in dsn and "${POSTGRES_PASSWORD" in dsn
    assert services["db-backup"]["environment"]["PGPASSWORD"].startswith("${")
    assert services["db-basebackup"]["environment"]["PGPASSWORD"].startswith("${")
    wal = services["wal-archiver"]["environment"]
    assert wal["S3_ACCESS_KEY"].startswith("${")
    assert wal["S3_SECRET_KEY"].startswith("${")


def credential_interpolations(text: str) -> list[str]:
    """Every ${POSTGRES_PASSWORD…}/${MINIO_ROOT_PASSWORD…} that carries a modifier.

    Returned as the literal offending interpolations, so both the base file and any
    overlay can be scanned by the same predicate.
    """
    return [
        f"${{{name}{suffix}}}"
        for name, suffix in re.findall(
            r"\$\{(POSTGRES_PASSWORD|MINIO_ROOT_PASSWORD)([^}]*)\}", text
        )
        if suffix
    ]


def test_no_datastore_password_falls_back_to_a_repo_default() -> None:
    """Q203 #33 残留 1：口令必须"不给就起不来"，而不是"不给就用仓里的弱默认"。

    刻意**不**在 base compose 用 `${VAR:?}`——compose 在解析期全局求值，会打断没设这
    两个变量的 overlay/彩排（Q185 记过同型坑；opt-in 的 monitoring overlay 里
    Grafana 口令仍用 `:?`，那是它独立成栈的理由）。裸 `${VAR}` 未设时展开为空串，
    交给 postgres/minio 自己启动即失败，报错出现在真正的责任方身上。
    """
    text = COMPOSE.read_text()
    assert credential_interpolations(text) == []
    # 用户名/库名可以留默认（不是凭证），口令一处都不行。
    assert "${POSTGRES_USER:-loom}" in text
    assert "${POSTGRES_PASSWORD:?" not in text


def test_the_credential_scan_can_fire() -> None:
    """扫描器自己也要被证明会响：只在真文件上跑过，等于没证明它看得见东西。"""
    assert credential_interpolations("P: ${POSTGRES_PASSWORD:-s3cret}") == [
        "${POSTGRES_PASSWORD:-s3cret}"
    ]
    assert credential_interpolations("P: ${MINIO_ROOT_PASSWORD:?set it}") == [
        "${MINIO_ROOT_PASSWORD:?set it}"
    ]
    assert credential_interpolations("P: ${POSTGRES_PASSWORD}") == []


def test_every_compose_file_is_free_of_credential_defaults() -> None:
    """Q204：base 干净不算干净——四个 overlay 谁日后塞回默认，这条一起判红。"""
    files = sorted((REPO_ROOT / "infra").glob("docker-compose*.yml"))
    assert len(files) >= 5, [f.name for f in files]  # base + 四个 overlay，glob 失效要立刻看见
    offenders = {
        f.name: credential_interpolations(f.read_text())
        for f in files
    }
    assert {k: v for k, v in offenders.items() if v} == {}, offenders


def test_rehearsal_scripts_supply_datastore_passwords() -> None:
    """去掉默认后，三套起 compose 栈的彩排必须自己注入，否则整栈起不来。"""
    for path in REHEARSAL_SCRIPTS:
        content = path.read_text()
        for var in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD"):
            assert f"export {var}=" in content, (path.name, var)
            assert f"${{{var}:-" in content, (path.name, var)


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
