"""Minimal liveness watchdog for the private beta single-host deployment
(Q144 checklist #5). Polls the backend health endpoint (internal network)
and the frontend root; failures are logged and, when LOOM_ALERT_WEBHOOK is
set, posted as a best-effort JSON webhook. The script never exits on probe
failure (alerting, not restarting); container health reflects the process.
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


def main() -> None:
    print(f"[watchdog] polling {BACKEND_URL} and {FRONTEND_URL} every {INTERVAL_SECONDS}s", flush=True)
    while True:
        for url in (BACKEND_URL, FRONTEND_URL):
            ok, detail = probe(url)
            if not ok:
                alert(url, detail)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
