"""Minimal liveness watchdog for the private beta single-host deployment
(Q144 checklist #5). Polls the backend health endpoint (internal network)
and the frontend root; failures are logged and, when LOOM_ALERT_WEBHOOK is
set, posted as a best-effort JSON webhook. The script never exits on probe
failure (alerting, not restarting); container health reflects the process.

Q185 adds the metric-consumption hop: when PROMETHEUS_ALERTS_URL is set (only
the monitoring overlay sets it, so the feature is inert when monitoring is off)
the watchdog forwards newly firing Prometheus alert rules through the very same
webhook. That replaced an Alertmanager container: Alertmanager 0.34.1 expands
neither `$(VAR)` nor `env://` in `webhook_configs.url`, so reusing
LOOM_ALERT_WEBHOOK there would have forced operators to maintain a second,
separately mounted URL file (verified with `amtool check-config`).
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

BACKEND_URL = os.environ.get("BACKEND_HEALTH_URL", "http://backend:8000/healthz")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://frontend:3000/")
ALERT_WEBHOOK = os.environ.get("LOOM_ALERT_WEBHOOK", "")
INTERVAL_SECONDS = float(os.environ.get("WATCHDOG_INTERVAL_SECONDS", "30"))
TIMEOUT_SECONDS = float(os.environ.get("WATCHDOG_TIMEOUT_SECONDS", "5"))
# 空即关闭整条转发链：monitoring overlay 未启用时不该为它每轮打一条失败日志。
PROMETHEUS_ALERTS_URL = os.environ.get("PROMETHEUS_ALERTS_URL", "")


def probe(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            ok = 200 <= resp.status < 400
            return ok, f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001 - probe must report any failure
        return False, str(exc)


def alert(target: str, detail: str) -> None:
    print(f"ALERT target={target} {detail}", flush=True)
    if not ALERT_WEBHOOK:
        return
    body = json.dumps(
        {
            "source": "loom-watchdog",
            "target": target,
            "detail": detail,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    ).encode()
    try:
        req = urllib.request.Request(ALERT_WEBHOOK, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - alerting is best-effort
        print(f"ALERT webhook delivery failed: {exc}", flush=True)


def fetch_json(url: str):
    """读 Prometheus API；任何失败返回 None，绝不拖垮探活主循环。"""
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - forwarding is best-effort
        print(f"[watchdog] prometheus query failed: {exc}", flush=True)
        return None


def firing_alerts(doc: dict) -> list[dict]:
    """只取 state=firing（pending 未过 `for:` 窗口，不该通知）。

    key 含 activeAt：同一告警重新触发（新 activeAt）视为新事件再通知一次。
    """
    out = []
    data = (doc or {}).get("data") or {}
    for item in data.get("alerts") or []:
        if item.get("state") != "firing":
            continue
        labels = item.get("labels") or {}
        annotations = item.get("annotations") or {}
        name = labels.get("alertname", "unknown")
        out.append(
            {
                "key": f"{name}|{labels.get('instance', '')}|{item.get('activeAt', '')}",
                "name": name,
                "severity": labels.get("severity", "warning"),
                "detail": annotations.get("description") or annotations.get("summary", ""),
            }
        )
    return out


def forward_fired(seen: set) -> list[dict]:
    """把未见过的 firing 告警转发到 LOOM_ALERT_WEBHOOK，复用探活同一通道与信封。"""
    if not PROMETHEUS_ALERTS_URL:
        return []
    doc = fetch_json(PROMETHEUS_ALERTS_URL)
    if doc is None:
        return []
    newly = []
    for fired in firing_alerts(doc):
        if fired["key"] in seen:
            continue
        seen.add(fired["key"])
        newly.append(fired)
        alert(
            f"prometheus:{fired['name']}",
            f"severity={fired['severity']} {fired['detail']}",
        )
    return newly


def main() -> None:
    print(
        f"[watchdog] polling {BACKEND_URL} and {FRONTEND_URL} every {INTERVAL_SECONDS}s"
        + (f", forwarding alerts from {PROMETHEUS_ALERTS_URL}" if PROMETHEUS_ALERTS_URL else ""),
        flush=True,
    )
    seen: set = set()
    while True:
        for url in (BACKEND_URL, FRONTEND_URL):
            ok, detail = probe(url)
            if not ok:
                alert(url, detail)
        forward_fired(seen)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
