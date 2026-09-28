"""MCP server 面（Q232）：把 A2A 的三个 plan 模式 skill 以 MCP 工具暴露给外部 agent。

目标规格＝MCP **2026-07-28** 修订，本文件里用到的规范事实（均取自官方规范页，逐条可回查）：

- 该修订**移除协议级 sessions 与 `Mcp-Session-Id` 头**；
- **移除 `initialize`／`notifications/initialized` 握手**，服务端 **MUST** 实现 `server/discover`；
- 每个请求在 `_meta` 里带协议版本与客户端能力，客户端身份走 `io.modelcontextprotocol/clientInfo`；
- **所有 result 必带 `resultType`**；`server/discover` 与 `tools/list` 同属可缓存操作，
  其 `complete` 结果 **MUST** 带 `ttlMs`（`>=0`）与 `cacheScope`；
- 工具执行可返回 `input_required`（配 `inputRequests`），客户端补参数后重试；
- 版本不支持时的错误码 `-32022`。

**刻意边界**（与 Q150 A2A 第一阶段同口径）：只做 plan，不发证、不花真 token、不越人工 Gate。
`server/discover` 的字段集按官方结构对齐（Q235，见 `discover_result()`）。
"""

from __future__ import annotations

from typing import Any

from app.core.a2a.skills import list_skill_ids, run_plan_skill

PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = [PROTOCOL_VERSION]
SERVER_INFO = {"name": "loom", "version": "0.1"}

_ERROR_METHOD_NOT_FOUND = -32601
_ERROR_INVALID_PARAMS = -32602
_ERROR_VERSION_UNSUPPORTED = -32022

# 工具 id 用下划线名。官方约束为 **SHOULD** 级：长度 1–128、大小写敏感、仅允许
# `A-Z a-z 0-9 _ - .`、服务端内唯一（`server/tools#tool-names`，Q234 取回）。本仓的
# `[a-z0-9_]` 是其严格子集 ⇒ 合规；与 A2A skill id 的对应关系见 docs/22 §3.3。
_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "loom_plan_generate_content",
        "title": "内容生成规划（plan only）",
        "description": "为某租户的某产品规划段 12 内容生成批次与将经过的人工 Gate；只出计划，不生成正文、不发证。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "description": "租户 id"},
                "product_id": {"type": "string", "description": "产品/内容空间锚点 id"},
            },
            "required": ["tenant_id", "product_id"],
            "additionalProperties": False,
        },
        "skill": "generate-content",
    },
    {
        "name": "loom_plan_compliance_check",
        "title": "合规检查规划（plan only）",
        "description": "为某成品列出将执行的合规清洗检查项，并标注哪些是 advisory、哪些须人工 Gate 裁决；不写库。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "content_id": {"type": "string"},
            },
            "required": ["tenant_id", "content_id"],
            "additionalProperties": False,
        },
        "skill": "compliance-check",
    },
    {
        "name": "loom_plan_effect_backfill",
        "title": "效果回填规划（plan only）",
        "description": "按 Q128 客户通道语义规划一批效果数据回填的核对点（幂等键、整批 all-or-nothing、孤儿路径）；不落库。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string"},
                "content_id": {"type": "string"},
            },
            "required": ["tenant_id", "content_id"],
            "additionalProperties": False,
        },
        "skill": "effect-backfill",
    },
)

_SKILL_BY_TOOL = {t["name"]: t["skill"] for t in _TOOLS}
_PUBLIC_TOOLS = [{k: v for k, v in t.items() if k != "skill"} for t in _TOOLS]

# 两张表都是静态的 ⇒ 允许客户端缓存；5 分钟与 A2A 卡片 `Cache-Control: max-age=300` 同值。
_CACHE_TTL_MS = 300_000
# 两表对所有通过 Q88 Agent Key 的调用方一致，但面本身在鉴权之后 ⇒ 取 private 而非 public。
_CACHE_SCOPE = "private"


def tool_names() -> list[str]:
    return list(_SKILL_BY_TOOL)


def discover_result() -> dict[str, Any]:
    """`server/discover` 响应，字段集按官方 2026-07-28 结构（Q235 对齐）。

    官方结构（`server/discover` 页）：`resultType` ＋ `supportedVersions`（数组）＋
    `capabilities` ＋ `_meta["io.modelcontextprotocol/serverInfo"]`（`{name,version}`）＋
    `instructions`（可选）＋ `ttlMs` ＋ `cacheScope`。caching 页另规定：本操作与
    `tools/list` 同属可缓存操作，`resultType:"complete"` 的结果 **MUST** 带
    `ttlMs`（`>=0`）与 `cacheScope`。
    """
    return {
        "resultType": "complete",
        "supportedVersions": SUPPORTED_PROTOCOL_VERSIONS,
        "capabilities": {"tools": {"listChanged": False}, "prompts": {}, "resources": {}},
        "instructions": "Loom 只暴露 plan 模式工具：不生成正文、不发 final_id、不代替人工 Gate。",
        "_meta": {"io.modelcontextprotocol/serverInfo": SERVER_INFO},
        "ttlMs": _CACHE_TTL_MS,
        "cacheScope": _CACHE_SCOPE,
    }


def tools_list_result() -> dict[str, Any]:
    return {
        "resultType": "complete",
        "tools": _PUBLIC_TOOLS,
        "nextCursor": None,
        "ttlMs": _CACHE_TTL_MS,
        "cacheScope": _CACHE_SCOPE,
    }


def _error(code: int, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": content}]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """跑一个 plan skill 并映射到 MCP 结果；缺参数 ⇒ `input_required`（不是错误）。"""
    skill = _SKILL_BY_TOOL.get(name)
    if skill is None:
        return {
            "resultType": "complete",
            "content": _text(f"unknown tool: {name}; available: {', '.join(tool_names())}"),
            "isError": True,
        }
    plan = run_plan_skill(skill, dict(arguments or {}))
    state = plan.get("state")
    if state == "input-required":
        missing = [part.strip() for part in str(plan.get("message", "")).split(":", 1)[-1].split(",")]
        return {
            "resultType": "input_required",
            "content": _text(plan.get("message", "")),
            "inputRequests": [
                {"name": key, "reason": "required parameter missing", "required": True}
                for key in [m for m in missing if m]
            ],
            "isError": False,
        }
    if state == "failed":
        return {"resultType": "complete", "content": _text(plan.get("message", "")), "isError": True}
    return {
        "resultType": "complete",
        "content": _text(plan.get("summary", "")),
        "structuredContent": {k: v for k, v in plan.items() if k not in {"state"}},
        "isError": False,
    }


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    """JSON-RPC 2.0 分发（纯函数：不起 DB、不调链路、不花 token）。"""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        return _error(_ERROR_INVALID_PARAMS, "invalid JSON-RPC 2.0 request")

    method = payload["method"]
    params = payload.get("params") or {}
    meta = params.get("_meta") or payload.get("_meta") or {}
    asked = meta.get("protocolVersion")
    if asked and asked not in SUPPORTED_PROTOCOL_VERSIONS:
        return _error(_ERROR_VERSION_UNSUPPORTED, f"unsupported protocolVersion {asked!r}; supported: {', '.join(SUPPORTED_PROTOCOL_VERSIONS)}")

    if method in ("server/discover", "initialize"):
        if method == "initialize":
            return _error(
                _ERROR_METHOD_NOT_FOUND,
                "the initialize handshake was removed in 2026-07-28; call server/discover instead",
            )
        return {"result": discover_result()}
    if method == "tools/list":
        return {"result": tools_list_result()}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error(_ERROR_INVALID_PARAMS, "tools/call requires params.name")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            # 刻意不写 `params.get("arguments") or {}`：`[]`/`0`/`""` 都是假值，会被当"没传"放过去。
            return _error(_ERROR_INVALID_PARAMS, "tools/call params.arguments must be an object")
        return {"result": call_tool(name, arguments)}
    if method == "ping":
        return {"result": {"resultType": "complete", "io.modelcontextprotocol/serverInfo": SERVER_INFO}}
    return _error(_ERROR_METHOD_NOT_FOUND, f"method not found: {method}")


def known_skills() -> list[str]:
    return list_skill_ids()
