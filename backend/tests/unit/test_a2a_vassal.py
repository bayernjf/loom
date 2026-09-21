"""Q150 A2A 封臣端点单测：卡片、plan skills、JSON-RPC 生命周期（纯内存层）。"""

from __future__ import annotations

import pytest

from app.core.a2a import rpc
from app.core.a2a.card import FEALTY, SKILLS, build_agent_card
from app.core.a2a.skills import list_skill_ids, run_plan_skill


def user_message(skill: str, params: dict, run_id: str | None = None) -> dict:
    message: dict = {"role": "user", "parts": [{"kind": "data", "data": {"skill": skill, **params}}]}
    if run_id:
        message["metadata"] = {"x-zeus-runId": run_id}
    return message


@pytest.fixture(autouse=True)
def _clean_store():
    rpc.reset_for_tests()
    yield
    rpc.reset_for_tests()


class TestCard:
    def test_card_exposes_fealty_and_three_plan_skills(self):
        card = build_agent_card()
        assert card["name"] == "loom"
        assert FEALTY["swornTo"] == "zeus"
        assert FEALTY["domain"] == "content-production"
        assert FEALTY["dataRealms"] == ["enterprise"]
        assert FEALTY["dataPolicy"] == "read-task-scope"
        assert FEALTY["escalationPolicy"] == "auto"
        assert FEALTY["sla"]["ackSeconds"] == 10
        assert [skill["id"] for skill in SKILLS] == ["generate-content", "compliance-check", "effect-backfill"]
        assert card["capabilities"]["streaming"] is True

    def test_plan_only_promise_is_in_fealty_notes(self):
        assert "never" in FEALTY["notes"] and "human gate" in FEALTY["notes"]


class TestSkills:
    def test_plan_skill_completes_with_required_params(self):
        result = run_plan_skill("generate-content", {"tenant_id": "t1", "product_id": "p1"})
        assert result["state"] == "completed"
        assert len(result["steps"]) >= 3

    def test_missing_params_return_input_required(self):
        result = run_plan_skill("compliance-check", {"tenant_id": "t1"})
        assert result["state"] == "input-required"
        assert "content_id" in result["message"]

    def test_unknown_skill_fails_with_available_list(self):
        result = run_plan_skill("nope", {})
        assert result["state"] == "failed"
        for skill_id in list_skill_ids():
            assert skill_id in result["message"]


class TestRpcLifecycle:
    def _send(self, message: dict, events: list | None = None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tasks/send", "params": {"message": message}}
        return rpc.handle_jsonrpc(payload, on_event=events.append if events is not None else None)

    def test_full_lifecycle_submitted_working_completed(self):
        events: list = []
        response = self._send(user_message("generate-content", {"tenant_id": "t1", "product_id": "p1"}), events)
        task = response["result"]
        assert task["kind"] == "task"
        assert task["status"]["state"] == "completed"
        states = [e["status"]["state"] for e in events if e["kind"] == "status-update"]
        assert states == ["submitted", "working", "completed"]
        assert any(e["kind"] == "artifact-update" for e in events)

    def test_report_is_plan_only_and_free(self):
        response = self._send(user_message("effect-backfill", {"tenant_id": "t1", "content_id": "c1"}))
        artifact = response["result"]["artifacts"][0]
        report = artifact["x-zeus-report"]
        assert report["cost"]["llmTokens"] == 0
        assert any("no chain mutation" in evidence for evidence in report["evidence"])
        assert any("no gate bypass" in evidence for evidence in report["evidence"])

    def test_run_id_echoed_on_all_events(self):
        events: list = []
        self._send(user_message("compliance-check", {"tenant_id": "t1", "content_id": "c1"}, run_id="zeus-run-9"), events)
        assert events
        for event in events:
            assert event["x-zeus"] == {"runId": "zeus-run-9"}

    def test_input_required_missing_params(self):
        response = self._send(user_message("generate-content", {}))
        assert response["result"]["status"]["state"] == "input-required"

    def test_get_and_cancel(self):
        # Plan mode runs synchronously, so a fully-paramed task lands in
        # completed (terminal) and cannot be canceled. Send a task missing
        # required params instead: it stops in input-required (non-terminal)
        # and is therefore cancellable — this exercises the get/cancel path.
        response = self._send(user_message("generate-content", {}))
        assert response["result"]["status"]["state"] == "input-required"
        task_id = response["result"]["id"]
        fetched = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tasks/get", "params": {"id": task_id}})
        assert fetched["result"]["id"] == task_id
        canceled = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 3, "method": "tasks/cancel", "params": {"id": task_id}})
        assert canceled["result"]["status"]["state"] == "canceled"
        again = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 4, "method": "tasks/cancel", "params": {"id": task_id}})
        assert again["error"]["code"] == -32002

    def test_unknown_task_and_method_errors(self):
        missing = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "nope"}})
        assert missing["error"]["code"] == -32001
        bogus = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "bogus"})
        assert bogus["error"]["code"] == -32601

    def test_invalid_message_params(self):
        response = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tasks/send", "params": {"message": {"role": "agent", "parts": []}}})
        assert response["error"]["code"] == -32602
        no_skill = rpc.handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tasks/send", "params": {"message": user_message("", {})}})
        assert no_skill["error"]["code"] == -32602
