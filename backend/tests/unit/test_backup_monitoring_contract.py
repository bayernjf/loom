"""Contract guard for the minimum backup and monitoring setup
(Q144 checklist #5).

Statically checks that compose runs a pg_dump backup loop with retention and
a liveness watchdog with best-effort webhook alerting, and that container
logs are rotated. The watchdog probe/alert behavior is exercised against
real loopback HTTP servers.

Q185 adds the metric-consumption half: the monitoring overlay shape, and — the
load-bearing guard — that alert_rules.yml only ever references metrics the
process actually registers, so no future rule can be written against a
fabricated name.
"""

import http.server
import re
import socketserver
import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPO_ROOT / "infra" / "backup" / "backup.sh"
WATCHDOG = REPO_ROOT / "infra" / "monitoring" / "watchdog.py"
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"
MONITORING_COMPOSE = REPO_ROOT / "infra" / "docker-compose.monitoring.yml"
ALERT_RULES = REPO_ROOT / "infra" / "monitoring" / "alert_rules.yml"


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"]


class _ComposeLoader(yaml.SafeLoader):
    """compose 的 `!reset` / `!override` / `!merge` 是私有标签，safe_load 不认。"""


def _construct_tagged(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


for _tag in ("!reset", "!override", "!merge"):
    _ComposeLoader.add_constructor(_tag, _construct_tagged)


def _compose_overlay(relpath: str) -> dict:
    return yaml.load(
        (REPO_ROOT / "infra" / relpath).read_text(), Loader=_ComposeLoader
    )


def test_compose_runs_backup_loop_with_retention_and_volume() -> None:
    backup = _services()["db-backup"]
    assert "pgvector:pg16" in backup["image"]
    assert backup["entrypoint"] == ["/bin/sh", "/scripts/backup.sh"]
    assert "pgbackups:/backups" in backup["volumes"]
    assert "./backup:/scripts:ro" in backup["volumes"]
    env = backup["environment"]
    assert env["PGHOST"] == "postgres"
    assert env["RETENTION_DAYS"].endswith(":-7}")
    assert backup["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_backup_script_dumps_prunes_and_loops() -> None:
    content = BACKUP_SCRIPT.read_text()
    assert "pg_dump" in content
    assert "-mtime" in content and "RETENTION_DAYS" in content
    assert "sleep \"$BACKUP_INTERVAL_SECONDS\"" in content
    assert content.index("pg_dump") < content.index("find")


def test_compose_runs_watchdog_for_backend_and_frontend() -> None:
    watchdog = _services()["watchdog"]
    env = watchdog["environment"]
    assert env["BACKEND_HEALTH_URL"] == "http://backend:8000/healthz"
    assert env["FRONTEND_URL"] == "http://frontend:3000/"
    assert env["LOOM_ALERT_WEBHOOK"] == "${LOOM_ALERT_WEBHOOK:-}"
    assert watchdog["command"] == ["python", "/monitor/watchdog.py"]
    assert watchdog["depends_on"]["backend"]["condition"] == "service_healthy"


def test_all_services_rotate_json_logs_and_frontend_has_healthcheck() -> None:
    services = _services()
    for name, service in services.items():
        logging = service.get("logging")
        assert logging is not None, f"{name} lacks logging config"
        assert logging["driver"] == "json-file"
        assert logging["options"]["max-size"] == "10m"
        assert logging["options"]["max-file"] == "3"
    test_cmd = str(services["frontend"]["healthcheck"]["test"])
    assert "http://localhost:3000/" in test_cmd


def _load_watchdog():
    import importlib.util

    spec = importlib.util.spec_from_file_location("loom_watchdog", WATCHDOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _watchdog_module(monkeypatch):
    """Fresh module per test: PROMETHEUS_ALERTS_URL 等是 import 期读 env 的模块常量。"""
    monkeypatch.delenv("PROMETHEUS_ALERTS_URL", raising=False)
    monkeypatch.delenv("LOOM_ALERT_WEBHOOK", raising=False)
    return _load_watchdog()


@pytest.fixture()
def watchdog_module():
    return _load_watchdog()


def _serve(status: int = 200) -> int:
    handler = http.server.SimpleHTTPRequestHandler

    class _Handler(handler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()

    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server.server_address[1]


def test_watchdog_probe_reports_status_and_failure(watchdog_module) -> None:
    port = _serve(200)
    ok, detail = watchdog_module.probe(f"http://127.0.0.1:{port}/")
    assert ok and "200" in detail

    ok, detail = watchdog_module.probe("http://127.0.0.1:1/")
    assert not ok and detail


def test_watchdog_alert_posts_webhook_and_swallows_delivery_errors(
    watchdog_module, monkeypatch, capsys
) -> None:
    received: list[dict] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            import json

            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # silence test server logs
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/hook"

    monkeypatch.setattr(watchdog_module, "ALERT_WEBHOOK", url)
    watchdog_module.alert("test-target", "boom")
    assert received and received[0]["target"] == "test-target"
    assert "ALERT target=test-target" in capsys.readouterr().out

    monkeypatch.setattr(watchdog_module, "ALERT_WEBHOOK", "http://127.0.0.1:1/")
    watchdog_module.alert("test-target", "boom")  # must not raise


# ---------------------------------------------------------------------------
# Q185 指标消费侧
# ---------------------------------------------------------------------------

# Prometheus 选择器语法里指标名总是紧跟 `{`（标签）或 `[`（区间向量）；
# 函数调用跟 `(`，标签名跟在 `{` 之后，故两者都不会被这条正则误抓。
_METRIC_REF = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*[\{\[]")
_SERIES_SUFFIXES = ("_bucket", "_sum", "_count")


def _registered_metric_names() -> set[str]:
    from app.core.metrics.middleware import REGISTRY

    names = set()
    for name in REGISTRY._metrics:
        names.add(name)
        for suffix in _SERIES_SUFFIXES:
            names.add(name + suffix)
    return names


def _alert_rules() -> list[dict]:
    doc = yaml.safe_load(ALERT_RULES.read_text())
    return [rule for group in doc["groups"] for rule in group["rules"]]


def test_monitoring_overlay_is_separate_and_gated() -> None:
    """Grafana 口令的 `:?` 护栏只能待在 opt-in overlay 里。

    compose 在解析期对全文件做插值、与 profile 是否激活无关，护栏若放 base
    会连带打断不开监控的默认部署路径（Q185 演练实测踩到）。
    """
    base = yaml.safe_load(COMPOSE.read_text())
    assert "prometheus" not in base["services"]
    assert "grafana" not in base["services"]
    assert "${LOOM_GRAFANA_ADMIN_PASSWORD:?" not in COMPOSE.read_text()

    overlay = yaml.safe_load(MONITORING_COMPOSE.read_text())
    services = overlay["services"]
    # watchdog 只被 overlay 打了一个 env 补丁，本身不是新容器。
    assert set(services) == {"prometheus", "grafana", "watchdog"}
    grafana_env = services["grafana"]["environment"]
    assert "${LOOM_GRAFANA_ADMIN_PASSWORD:?" in grafana_env["GF_SECURITY_ADMIN_PASSWORD"]
    # 无默认口令可回退：不允许内置弱口令。
    assert "${LOOM_GRAFANA_ADMIN_PASSWORD:-" not in str(grafana_env)


def test_monitoring_overlay_services_rotate_logs() -> None:
    """base 的全服务日志轮转遍历覆盖不到 overlay，故在此补齐同一约束。

    只约束真正起容器的服务（声明了 image）；overlay 里给 watchdog 打 env 的片段
    不是容器定义，compose 会把它并进 base 里已带 logging 的 watchdog。
    """
    services = yaml.safe_load(MONITORING_COMPOSE.read_text())["services"]
    for name, service in services.items():
        if "image" not in service:
            continue
        logging = service.get("logging")
        assert logging is not None, f"{name} lacks logging config"
        assert logging["driver"] == "json-file"
        assert logging["options"]["max-size"] == "10m"
        assert logging["options"]["max-file"] == "3"


def test_monitoring_services_publish_no_new_host_ports() -> None:
    """Q145 收敛发布口：只沿用 Q181 已有的 9090，Grafana 不额外开宿主端口。"""
    services = yaml.safe_load(MONITORING_COMPOSE.read_text())["services"]
    assert services["prometheus"]["ports"] == ["9090:9090"]
    assert "ports" not in services["grafana"]


def test_prometheus_mounts_rules_without_an_alerting_block() -> None:
    services = yaml.safe_load(MONITORING_COMPOSE.read_text())["services"]
    volumes = services["prometheus"]["volumes"]
    assert "./monitoring/alert_rules.yml:/etc/prometheus/alert_rules.yml:ro" in volumes

    conf = yaml.safe_load((REPO_ROOT / "infra" / "monitoring" / "prometheus.yml").read_text())
    assert conf["rule_files"] == ["/etc/prometheus/alert_rules.yml"]
    # 无投递对象：转发由 watchdog 轮询 /api/v1/alerts，Prometheus 不再对外告警。
    assert "alerting" not in conf


def test_alert_rules_reference_only_registered_metrics() -> None:
    """事实纪律守卫：规则里出现的每个指标名都必须是进程真实注册（或其派生序列）。

    Q181 目前只有 up / http_requests_total / http_request_duration_seconds 三族、
    全仓零业务打点，因此任何"队列积压/job failed/锁易主"式规则都是臆造指标名。
    """
    registered = _registered_metric_names()
    referenced = set()
    for rule in _alert_rules():
        referenced.update(_METRIC_REF.findall(str(rule["expr"])))
    assert referenced, "no metric referenced - the regex stopped matching real rules"
    unknown = sorted(referenced - registered)
    assert unknown == [], f"alert rules reference unregistered metrics: {unknown}"


def test_alert_rules_cover_the_three_RED_signals() -> None:
    rules = {rule["alert"]: rule for rule in _alert_rules()}
    assert set(rules) == {
        "LoomHigh5xxRatio",
        "LoomHighP99Latency",
        "LoomBackendUnreachable",
    }
    for rule in rules.values():
        assert rule["labels"]["severity"] in {"critical", "warning"}
        assert rule["annotations"]["summary"]
        assert "for" in rule


def test_alert_delivery_reuses_the_single_watchdog_webhook_channel() -> None:
    """Q185：告警投递不新开设施——由 watchdog 转发，与 Q146 探活共用同一 env 通道。

    刻意不引入 Alertmanager：0.34.1 的 webhook_configs.url 既不展开 `$(VAR)` 也不支持
    `env://`（`amtool check-config` 实测 `unsupported scheme`），复用到 LOOM_ALERT_WEBHOOK
    就得再让运维单独挂一个 URL 文件，配置面翻倍。
    """
    compose_text = COMPOSE.read_text() + MONITORING_COMPOSE.read_text()
    # 只看非注释行：两处注释会解释"为什么不用 Alertmanager"，提及不等于使用。
    executable = "\n".join(
        line for line in compose_text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "alertmanager" not in executable.lower()
    assert "LOOM_ALERT_WEBHOOK" in compose_text

    # 未开监控时转发链必须完全惰性：base 里不得出现 Prometheus 转发 env。
    assert "PROMETHEUS_ALERTS_URL" not in COMPOSE.read_text()
    overlay = yaml.safe_load(MONITORING_COMPOSE.read_text())
    assert (
        overlay["services"]["watchdog"]["environment"]["PROMETHEUS_ALERTS_URL"]
        == "http://prometheus:9090/api/v1/alerts"
    )


def test_watchdog_forwarding_is_inert_without_the_overlay_env(monkeypatch, capsys) -> None:
    watchdog = _watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog, "PROMETHEUS_ALERTS_URL", "")
    assert watchdog.forward_fired(set()) == []
    assert "ALERT" not in capsys.readouterr().out


def test_watchdog_forwards_only_firing_alerts_once_each(monkeypatch, capsys) -> None:
    watchdog = _watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog, "PROMETHEUS_ALERTS_URL", "http://prometheus:9090/api/v1/alerts")
    monkeypatch.setattr(watchdog, "ALERT_WEBHOOK", "")  # 只验日志侧信封
    doc = {
        "data": {
            "alerts": [
                {"state": "pending", "labels": {"alertname": "LoomHigh5xxRatio"}},
                {
                    "state": "firing",
                    "activeAt": "2026-09-25T00:00:00Z",
                    "labels": {"alertname": "LoomBackendUnreachable", "severity": "critical"},
                    "annotations": {"description": "scrape failed 1m"},
                },
            ]
        }
    }
    monkeypatch.setattr(watchdog, "fetch_json", lambda url: doc)

    seen: set = set()
    newly = watchdog.forward_fired(seen)
    assert [a["name"] for a in newly] == ["LoomBackendUnreachable"]
    out = capsys.readouterr().out
    assert "ALERT target=prometheus:LoomBackendUnreachable severity=critical" in out
    # 同一 activeAt 再来一轮不得重复通知。
    assert watchdog.forward_fired(seen) == []
    # 重新触发（新 activeAt）视为新事件。
    doc["data"]["alerts"][1]["activeAt"] = "2026-09-25T01:00:00Z"
    assert len(watchdog.forward_fired(seen)) == 1


def test_watchdog_forwarding_survives_prometheus_being_down(monkeypatch, capsys) -> None:
    """Prometheus 不可达只打印、不抛出：探活主循环绝不能被转发链拖死。"""
    watchdog = _watchdog_module(monkeypatch)
    monkeypatch.setattr(watchdog, "PROMETHEUS_ALERTS_URL", "http://127.0.0.1:1/api/v1/alerts")
    assert watchdog.forward_fired(set()) == []
    assert "prometheus query failed" in capsys.readouterr().out


def test_monitoring_dashboard_provisioning_mounts_and_is_wired() -> None:
    services = yaml.safe_load(MONITORING_COMPOSE.read_text())["services"]
    assert (
        "./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro"
        in services["grafana"]["volumes"]
    )
    base = REPO_ROOT / "infra" / "monitoring" / "grafana" / "provisioning"
    ds = yaml.safe_load((base / "datasources" / "loom.yml").read_text())
    assert ds["datasources"][0]["uid"] == "loom-prom"
    assert ds["datasources"][0]["url"] == "http://prometheus:9090"

    provider = yaml.safe_load((base / "dashboards" / "loom.yml").read_text())
    assert provider["providers"][0]["options"]["path"] == "/etc/grafana/provisioning/dashboards"

    import json

    dash = json.loads((base / "dashboards" / "loom-http.json").read_text())
    assert dash["uid"] == "loom-http"
    registered = _registered_metric_names()
    for panel in dash["panels"]:
        for target in panel["targets"]:
            for name in _METRIC_REF.findall(str(target["expr"])):
                assert name in registered, f"panel {panel['id']} uses unregistered {name}"


def test_wal_archiver_minio_dependency_is_optional() -> None:
    """Q182 的 wal-archiver 依赖 minio，而 staging/ha overlay 把 minio 挪进非激活
    profile；`required` 默认 true 会让整个 compose project 判 invalid（Q185 演练实测）。
    """
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    dep = services["wal-archiver"]["depends_on"]["minio"]
    assert dep["required"] is False

    staging = _compose_overlay("docker-compose.staging.yml")
    assert staging["services"]["wal-archiver"]["profiles"] == ["unused-in-rehearsal"]


def test_wal_archive_volume_ownership_is_prepared_by_root_init() -> None:
    """Q185：归档卷属主必须由一次性 root 容器准备，不能指望 initdb.d 脚本。

    官方 postgres 镜像把 /docker-entrypoint-initdb.d 下的 .sh 以 postgres（uid 999）
    身份执行；空命名卷挂载点默认 root:root，脚本内 chown/chmod 双双 EPERM，被
    `set -e` 打死 → postgres exit 1 → 全新卷的 `docker compose up` 必挂。
    """
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    init = services["wal-archive-init"]
    assert init["user"] == "root"
    assert "chown 999:999 /wal-archive" in " ".join(init["entrypoint"])
    assert "walarchive:/wal-archive" in init["volumes"]
    assert init["restart"] == "no"
    assert services["postgres"]["depends_on"]["wal-archive-init"][
        "condition"
    ] == "service_completed_successfully"

    script = (REPO_ROOT / "infra" / "wal" / "init-replica-hba.sh").read_text()
    # 错误假设的修复动作不得回流到该脚本（只看非注释行，说明性注释可以提 chown）。
    executable = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    assert "chown" not in executable and "chmod" not in executable
    assert "host replication all all" in script
