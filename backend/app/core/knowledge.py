"""model-hub 知识库消费客户端（Tier0 M3-W3-5：loom 知识库首个消费试点）。

PRD F3 FR3-5「API-first 消费」：loom 经 hub project token 调
``POST /api/v1/knowledge/query``（契约见 model-hub ``docs/knowledge-api.md``），
把业务文档检索命中作为上下文注入内容生成（ARTICLE-GEN），让段12「懂业务文档」。

两面语义（本模块的契约核心）：
- 配置面 fail-closed：``LOOM_KNOWLEDGE_URL`` / ``LOOM_KNOWLEDGE_TOKEN`` 任一缺失
  ⇒ 功能整体停用，``query_knowledge`` 返回 None——不报错、不发请求、不注入；
- 运行面 fail-soft：超时 / HTTP 4xx-5xx / 非法响应 / 无命中 ⇒ 一律返回 None，
  绝不抛错。知识库是生成原料的增强项（advisory），不是生成主链的依赖项
  （与 ARTICLE-QC / ARTICLE-SEMANTIC-CHECK 的 Q57/Q121 定位同族）。

env（直读 os.environ，不是 Settings 字段 ⇒ 走可 source 的 backend/.env.shell
载体，Q239；不得放进 backend/.env，否则 Settings extra=forbid 进程起不来）：
- ``LOOM_KNOWLEDGE_URL``              hub 基址（如 ``http://localhost:8791``）；
- ``LOOM_KNOWLEDGE_TOKEN``            hub project token（``mh_…``，owner 维度隔离）；
- ``LOOM_KNOWLEDGE_TIMEOUT_SECONDS``  可选超时旋钮，默认 15s（与 ModelHubClient 默认一致）。

不重试（与 drivers.py 出站重试刻意不同）：drivers 的重试守护的是「生成可用性」
主路径；这里的一次调用只是原料增强，重试只会线性拖慢内容生成，超时即放弃。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

QUERY_PATH = "/api/v1/knowledge/query"
#: 检索条数：注入段保持精炼，top-k 命中前 3 条足够支撑事实校准。
DEFAULT_TOP_K = 3
#: 单条引用注入 prompt 的内容上限（字符），控制上下文膨胀。
CITATION_CONTENT_CAP = 300
#: 原料里用于拼检索词的原子文本上限（字符）。
QUERY_ATOM_CHARS = 200


@dataclass(frozen=True)
class KnowledgeCitation:
    """query 响应里的一条命中（字段对齐 knowledge-api.md 的 citations 项）。"""

    chunk_id: str
    doc_id: str
    title: str
    position: int | None
    score: float | None
    content: str


@dataclass(frozen=True)
class KnowledgeAnswer:
    """一次成功检索：answer 可为 None（hub 未配 answer alias 时），citations 必非空。"""

    query: str
    answer: str | None
    citations: list[KnowledgeCitation]


# ---------------- 配置（fail-closed） ----------------


def knowledge_settings() -> tuple[str, str] | None:
    """返回 (base_url, token)；任一缺失/空白 ⇒ None（功能停用）。"""
    url = os.getenv("LOOM_KNOWLEDGE_URL", "").strip()
    token = os.getenv("LOOM_KNOWLEDGE_TOKEN", "").strip()
    if not url or not token:
        return None
    return url.rstrip("/"), token


def _timeout_seconds(override: float | None) -> float:
    """优先级：调用参数 > env 旋钮 > 默认 15s（字符串默认经 float()，不新增浮点字面量）。"""
    if override is not None:
        return override
    return float(os.getenv("LOOM_KNOWLEDGE_TIMEOUT_SECONDS", "15"))


# ---------------- 查询（fail-soft） ----------------


async def query_knowledge(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    timeout: float | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> KnowledgeAnswer | None:
    """查 hub 知识库；停用/空查询词/失败/无命中 ⇒ None，本函数绝不抛错。

    ``transport`` 仅供单测注入（httpx.MockTransport），运行时恒 None 走真网络。
    """
    settings = knowledge_settings()
    if settings is None or not query.strip():
        return None
    base_url, token = settings
    try:
        async with httpx.AsyncClient(
            timeout=_timeout_seconds(timeout), transport=transport
        ) as client:
            resp = await client.post(
                f"{base_url}{QUERY_PATH}",
                json={"query": query, "top_k": top_k},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # 超时/网络/4xx/5xx/非法 JSON 全部 fail-soft：留一行日志便于排障，不打断主流程。
        logger.warning("knowledge query failed (fail-soft): %s", exc)
        return None
    return _parse_answer(query, data)


def _parse_answer(query: str, data: Any) -> KnowledgeAnswer | None:
    """宽松解析：非 dict / citations 缺失或空 / 无可用条目 ⇒ None（无命中不注入）。

    单条目内坏字段跳过或降级（title 缺省、position/score 置 None），不让个别
    畸形条目拖垮整次注入。
    """
    if not isinstance(data, dict):
        return None
    raw_citations = data.get("citations")
    if not isinstance(raw_citations, list):
        return None
    citations: list[KnowledgeCitation] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        citations.append(
            KnowledgeCitation(
                chunk_id=str(item.get("chunk_id", "")),
                doc_id=str(item.get("doc_id", "")),
                title=str(item.get("title", "") or "未命名文档"),
                position=_as_int(item.get("position")),
                score=_as_float(item.get("score")),
                content=content,
            )
        )
    if not citations:
        return None
    answer = data.get("answer")
    return KnowledgeAnswer(
        query=query,
        answer=answer if isinstance(answer, str) else None,
        citations=citations,
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------- 注入渲染 ----------------


def context_section(answer: KnowledgeAnswer) -> str:
    """把命中渲染为追加进生成原料的参考段：``[n]《标题》内容``，带出处编号。"""
    lines = ["业务文档参考（model-hub 知识库检索命中，仅供事实校准，出处见编号）："]
    for index, citation in enumerate(answer.citations, start=1):
        content = " ".join(citation.content.split())
        if len(content) > CITATION_CONTENT_CAP:
            content = content[:CITATION_CONTENT_CAP] + "…"
        lines.append(f"[{index}]《{citation.title}》{content}")
    return "\n".join(lines)
