"""docs/22（机器接入手册）⇄ 代码的漂移门（Q277）。

docs/22 是给外部接入方读的面说明书，它宣称的方法名／工具名／skill id／协议版本／门控 env
全部来自代码；而本仓对"报告类文档"没有任何门（docs/23 §11.8 登记的 P2）。这条守卫把
**可机读的那部分**改成机器判据：文档与代码不一致即判红，不再靠人工重扫。

刻意只钉"能机械核对的事实"，不钉措辞：散文怎么改都行，面本身改名不行。
"""

import pathlib
import re

from app.core.a2a.skills import list_skill_ids
from app.core.config import Settings
from app.core.mcp import server as mcp
from app.core.mcp.server import handle

BACKEND = pathlib.Path(__file__).resolve().parents[2]
DOCS_22 = (BACKEND.parent / "docs" / "22_外部系统接入手册_AgentKey_A2A_MCP.md").read_text()
DOCS_11 = (BACKEND.parent / "docs" / "11_API规范_OpenAPI.md").read_text()


def _rpc(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def test_protocol_version_is_documented_in_both_carriers() -> None:
    assert mcp.PROTOCOL_VERSION in DOCS_22
    assert mcp.PROTOCOL_VERSION in DOCS_11, "docs/11 §2.9 登记的规范版本与代码脱钩"


def test_documented_tools_are_exactly_the_code_tools() -> None:
    documented = set(re.findall(r"loom_plan_[a-z_]+", DOCS_22))
    assert documented == set(mcp.tool_names()), (
        f"文档列的工具与代码不一致：只在该文档={sorted(documented - set(mcp.tool_names()))}，"
        f"只在该代码={sorted(set(mcp.tool_names()) - documented)}"
    )


def test_documented_a2a_skills_match_the_executor() -> None:
    for skill_id in list_skill_ids():
        assert f"`{skill_id}`" in DOCS_22, f"skill {skill_id} 未写进 docs/22"
    assert "unknown skill: not-a-skill" not in DOCS_22


def test_supported_methods_documented_and_rejected_ones_stay_rejected() -> None:
    for method in ("server/discover", "tools/list", "tools/call"):
        assert method in DOCS_22, f"方法 {method} 的文档登记缺失"
        # 支持的方法绝不返回 method-not-found；tools/call 空参数是 -32602（参数错），那是另一回事。
        assert handle(_rpc(method)).get("error", {}).get("code") != -32601, (
            f"{method} 在代码里已不被支持，文档仍在宣传"
        )
    for removed in ("ping", "initialize", "logging/setLevel"):
        assert handle(_rpc(removed))["error"]["code"] == -32601, f"{removed} 竟被接受，文档却写已移除"
    assert "ping" in DOCS_22, "文档须明写 ping 已移除，否则接入方会照旧客户端来调"


def test_the_gate_and_its_default_are_documented_as_implemented() -> None:
    assert Settings.model_fields["mcp_enabled"].default is False, "默认值变了，docs/22 的『默认关』要同步"
    prefix = Settings.model_config["env_prefix"]
    env_name = f"{prefix}MCP_ENABLED"
    assert env_name == "LOOM_MCP_ENABLED", "env 前缀或字段名变了，docs/22 与 docs/11 写的门控名要同步"
    assert env_name in DOCS_22 and env_name in DOCS_11
    assert "MCP_ENABLED" not in (BACKEND / ".env.example").read_text(), (
        "运维旋钮按 Q135 起先例不入 .env.example；若有意改惯例，要连本守卫与 docs/22 一起改"
    )


def test_machine_credential_call_sites_stay_exactly_three() -> None:
    """docs/22 §0 与 §1 写"全仓 `require_agent_key` 的调用方恰好三处"——把它钉成机器判据。"""
    call_sites = sorted(
        path.relative_to(BACKEND).as_posix()
        for path in (BACKEND / "app").rglob("*.py")
        if re.search(r"await require_agent_key\(", path.read_text())
    )
    assert call_sites == [
        "app/core/a2a/router.py",
        "app/core/effects/router.py",
        "app/core/mcp/router.py",
    ], f"受机器凭证保护的面已变化：{call_sites}；docs/22 §0/§1 与 docs/11 §2.9 都要重扫"
