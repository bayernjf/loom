"""Agent Card 单一事实源（Q150）。修改能力声明只改本文件。"""

from app.core.config import get_settings

CARD_VERSION = "0.1.0"

SKILLS: list[dict] = [
    {
        "id": "generate-content",
        "name": "Plan content generation",
        "description": "Plan a segment-12 content generation run: advisory plan only, no chain mutation, no LLM token spend, human gates untouched.",
        "tags": ["chain-seg12", "plan-only", "human-gate"],
    },
    {
        "id": "compliance-check",
        "name": "Plan compliance cleaning",
        "description": "Plan a segment-11 compliance cleaning pass: advisory plan only, no chain mutation, results never bypass manual gates.",
        "tags": ["chain-seg11", "plan-only", "advisory"],
    },
    {
        "id": "effect-backfill",
        "name": "Plan effect feedback backfill",
        "description": "Plan a segment-13 effect backfill through the Q128 customer channel semantics: advisory plan only, no records written.",
        "tags": ["chain-seg13", "plan-only", "effect-loop"],
    },
]

FEALTY: dict = {
    "version": "1",
    "swornTo": "zeus",
    "domain": "content-production",
    "dataRealms": ["enterprise"],
    "dataPolicy": "read-task-scope",
    "reportBack": True,
    "escalationPolicy": "auto",
    "sla": {"ackSeconds": 10},
    "notes": (
        "Plan-mode vassal: every skill returns an advisory plan artifact and never "
        "touches the 13-segment chain, spends tokens, or bypasses a human gate. "
        "Task execution is JSON-RPC at POST /api/a2a/tasks protected by a Q88 "
        "agent API key. Task storage is in-memory per process."
    ),
}


def build_agent_card() -> dict:
    settings = get_settings()
    base = str(settings.public_base_url).rstrip("/") if getattr(settings, "public_base_url", None) else ""
    return {
        "name": "loom",
        "description": (
            "Private-domain content production whitelist platform (CHAIN_13). "
            "Vassal skills are plan-only: candidates and plans, human gates decide."
        ),
        "url": f"{base}/api/a2a/tasks",
        "version": CARD_VERSION,
        "capabilities": {"streaming": True, "pushNotifications": False, "stateTransitionHistory": True},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": SKILLS,
        "authentication": {"schemes": ["bearer"]},
        "preferredTransport": "JSONRPC",
        "x-zeus-fealty": FEALTY,
    }
