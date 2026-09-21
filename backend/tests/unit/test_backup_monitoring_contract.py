"""Contract guard for the minimum backup and monitoring setup
(Q144 checklist #5).

Statically checks that compose runs a pg_dump backup loop with retention and
a liveness watchdog with best-effort webhook alerting, and that container
logs are rotated. The watchdog probe/alert behavior is exercised against
real loopback HTTP servers.
"""

import http.server
import socketserver
import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKUP_SCRIPT = REPO_ROOT / "infra" / "backup" / "backup.sh"
WATCHDOG = REPO_ROOT / "infra" / "monitoring" / "watchdog.py"
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"]


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


@pytest.fixture()
def watchdog_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("loom_watchdog", WATCHDOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
