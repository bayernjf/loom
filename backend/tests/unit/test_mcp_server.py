"""Q232 MCP 分发器契约（纯单测，不起服务）。

钉三件事：2026-07-28 的必带字段在位（`resultType`／`ttlMs`／`cacheScope`）、
**只暴露 plan 三件工具**（发证与链路写口一律不在面上）、以及协议版本/未知方法/握手各有确定错误码。
"""

from app.core.mcp import server as mcp


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def test_tools_list_carries_the_2026_07_28_required_fields() -> None:
    result = mcp.handle(_rpc("tools/list"))["result"]
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 300_000 and result["cacheScope"] == "private"
    assert result["nextCursor"] is None
    names = [t["name"] for t in result["tools"]]
    assert names == [
        "loom_plan_generate_content",
        "loom_plan_compliance_check",
        "loom_plan_effect_backfill",
    ]
    for tool in result["tools"]:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["required"]
        assert "skill" not in tool, "内部 skill 映射不外泄"


def test_tools_expose_no_issuance_or_chain_writes() -> None:
    """治理红线：MCP 面只有 plan，绝不出现发证／链路写口。"""
    names = " ".join(mcp.tool_names()).lower()
    for forbidden in ("fcw", "assemble", "issue", "approve", "gate", "publish"):
        assert forbidden not in names, f"MCP 工具面出现越权动作：{forbidden}"
    discover = mcp.handle(_rpc("server/discover"))["result"]
    assert "plan" in discover["instructions"] and "final_id" in discover["instructions"]


def test_missing_parameters_come_back_as_input_required_not_an_error() -> None:
    result = mcp.handle(
        _rpc("tools/call", {"name": "loom_plan_compliance_check", "arguments": {"tenant_id": "t1"}})
    )["result"]
    assert result["resultType"] == "input_required"
    assert [r["name"] for r in result["inputRequests"]] == ["content_id"]
    assert result["isError"] is False


def test_full_call_returns_structured_plan() -> None:
    result = mcp.handle(
        _rpc(
            "tools/call",
            {"name": "loom_plan_effect_backfill", "arguments": {"tenant_id": "t1", "content_id": "c1"}},
        )
    )["result"]
    assert result["resultType"] == "complete" and result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert result["structuredContent"]["name"] == "effect-backfill-plan"
    assert result["structuredContent"]["steps"]


def test_unknown_tool_is_a_tool_error_not_a_protocol_error() -> None:
    result = mcp.handle(_rpc("tools/call", {"name": "nope", "arguments": {}}))["result"]
    assert result["isError"] is True and result["resultType"] == "complete"


def test_removed_handshake_and_unsupported_version_and_unknown_method_all_fail_closed() -> None:
    assert mcp.handle(_rpc("initialize"))["error"]["code"] == -32601
    bad_version = _rpc("tools/list", {"_meta": {"protocolVersion": "1999-01-01"}})
    assert mcp.handle(bad_version)["error"]["code"] == -32022
    assert mcp.handle(_rpc("resources/list"))["error"]["code"] == -32601
    assert mcp.handle({"method": "tools/list"})["error"]["code"] == -32602
    assert mcp.handle(_rpc("tools/call", {"arguments": {}}))["error"]["code"] == -32602
    assert mcp.handle(_rpc("tools/call", {"name": "x", "arguments": []}))["error"]["code"] == -32602


def test_supported_protocol_version_is_the_one_we_read_the_spec_at() -> None:
    assert mcp.PROTOCOL_VERSION == "2026-07-28"
    discover = mcp.handle(_rpc("server/discover"))["result"]
    assert discover["supportedVersions"] == ["2026-07-28"]
    assert discover["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "loom"


def test_discover_result_matches_the_official_2026_07_28_shape() -> None:
    """Q235：`server/discover` 的字段集与官方结构逐项一致（Q234 登记的 4 处出入已对齐）。"""
    result = mcp.handle(_rpc("server/discover"))["result"]
    assert set(result) == {
        "resultType",
        "supportedVersions",
        "capabilities",
        "instructions",
        "_meta",
        "ttlMs",
        "cacheScope",
    }, "多字段或少字段都是契约漂移"
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 300_000 and result["cacheScope"] == "private"
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == mcp.SERVER_INFO
    # 已移除的两处：官方 DiscoverResult 无单数 protocolVersion，身份也不再放 result 顶层
    assert "protocolVersion" not in result
    assert "io.modelcontextprotocol/serverInfo" not in result
