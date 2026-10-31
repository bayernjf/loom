"""知识库消费客户端单测（M3-W3-5，PRD F3 FR3-5）。

fake server ＝ ``httpx.MockTransport``：单测因此跑过**真实 httpx 请求/响应栈**
（与 video_drivers 的 transport 注入同型）。四面主场景：
- 命中：citations/answer 解析、请求带 Bearer token 与 query/top_k；
- 停用：env 缺失 ⇒ 不发请求直接 None（fail-closed）；
- 超时：ConnectTimeout ⇒ None（fail-soft）；
- 失败：HTTP 429/500/503、非法 JSON、citations 空/畸形 ⇒ None（fail-soft）。
"""

import json

import httpx
import pytest

from app.core import knowledge

HUB_BASE = "http://hub.test"
HUB_TOKEN = "mh_" + "a" * 64

HITS = {
    "query": "种草 douyin",
    "top_k": 3,
    "answer": "退款窗口为购买后 30 天 [1]。",
    "reranked": True,
    "citations": [
        {
            "chunk_id": "chk_1",
            "doc_id": "doc_1",
            "title": "退款政策",
            "position": 0,
            "score": 0.93,
            "content": "购买后 30 天可退款。",
        },
        {
            "chunk_id": "chk_2",
            "doc_id": "doc_2",
            "title": "品牌规范",
            "position": 2,
            "score": 0.71,
            "content": "  品牌\n主色 为 深蓝。 ",
        },
    ],
}


@pytest.fixture
def hub_env(monkeypatch):
    monkeypatch.setenv("LOOM_KNOWLEDGE_URL", HUB_BASE)
    monkeypatch.setenv("LOOM_KNOWLEDGE_TOKEN", HUB_TOKEN)


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ---------------- 配置面（fail-closed） ----------------


@pytest.mark.parametrize(
    "url,token",
    [("", ""), (HUB_BASE, ""), ("", HUB_TOKEN), ("   ", "   ")],
)
def test_knowledge_settings_missing_env_disables(monkeypatch, url, token):
    monkeypatch.delenv("LOOM_KNOWLEDGE_URL", raising=False)
    monkeypatch.delenv("LOOM_KNOWLEDGE_TOKEN", raising=False)
    if url:
        monkeypatch.setenv("LOOM_KNOWLEDGE_URL", url)
    if token:
        monkeypatch.setenv("LOOM_KNOWLEDGE_TOKEN", token)
    assert knowledge.knowledge_settings() is None


def test_knowledge_settings_present(hub_env):
    assert knowledge.knowledge_settings() == (HUB_BASE, HUB_TOKEN)


def test_timeout_seconds_precedence(monkeypatch):
    assert knowledge._timeout_seconds(2.5) == 2.5
    monkeypatch.setenv("LOOM_KNOWLEDGE_TIMEOUT_SECONDS", "7")
    assert knowledge._timeout_seconds(None) == 7.0
    monkeypatch.delenv("LOOM_KNOWLEDGE_TIMEOUT_SECONDS", raising=False)
    assert knowledge._timeout_seconds(None) == 15.0
    monkeypatch.setenv("LOOM_KNOWLEDGE_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(ValueError):
        knowledge._timeout_seconds(None)


# ---------------- 查询面（fail-soft） ----------------


async def test_query_hits_parse_citations_and_request_shape(hub_env):
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=HITS)

    answer = await knowledge.query_knowledge(
        "种草 douyin", transport=_mock(handler)
    )
    assert answer is not None
    assert answer.query == "种草 douyin"
    assert answer.answer == "退款窗口为购买后 30 天 [1]。"
    assert [c.title for c in answer.citations] == ["退款政策", "品牌规范"]
    assert answer.citations[0].score == pytest.approx(0.93)
    assert answer.citations[1].position == 2
    assert seen["url"] == f"{HUB_BASE}/api/v1/knowledge/query"
    assert seen["auth"] == f"Bearer {HUB_TOKEN}"
    assert seen["body"] == {"query": "种草 douyin", "top_k": 3}


async def test_query_disabled_without_env_sends_nothing(monkeypatch):
    monkeypatch.delenv("LOOM_KNOWLEDGE_URL", raising=False)
    monkeypatch.delenv("LOOM_KNOWLEDGE_TOKEN", raising=False)
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(200, json=HITS)

    assert await knowledge.query_knowledge("q", transport=_mock(handler)) is None
    assert not called


async def test_query_timeout_fail_soft(hub_env):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom", request=request)

    assert await knowledge.query_knowledge("q", transport=_mock(handler)) is None


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_query_http_error_fail_soft(hub_env, status):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "code"})

    assert await knowledge.query_knowledge("q", transport=_mock(handler)) is None


async def test_query_malformed_json_fail_soft(hub_env):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json{")

    assert await knowledge.query_knowledge("q", transport=_mock(handler)) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"citations": []},
        {"citations": "not-a-list"},
        {},
        "not-a-dict",
        # 全是坏条目（非 dict / content 缺失 / 空白）⇒ 无可用命中。
        {"citations": ["nope", {"no_content": 1}, {"content": "   "}]},
    ],
)
async def test_query_no_usable_hits_is_none(hub_env, payload):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    assert await knowledge.query_knowledge("q", transport=_mock(handler)) is None


async def test_query_malformed_entries_skipped_fields_degraded(hub_env):
    payload = {
        "answer": 42,  # 非 str ⇒ answer 归一为 None
        "citations": [
            "not-dict",  # 跳过
            {"content": "   "},  # 空白跳过
            {"content": "有效命中"},  # 最小可用：title 缺省、position/score 缺省
        ],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    answer = await knowledge.query_knowledge("q", transport=_mock(handler))
    assert answer is not None
    assert answer.answer is None
    assert len(answer.citations) == 1
    assert answer.citations[0].title == "未命名文档"
    assert answer.citations[0].position is None
    assert answer.citations[0].score is None


async def test_query_blank_query_skips(hub_env):
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=HITS)

    assert await knowledge.query_knowledge("   ", transport=_mock(handler)) is None


# ---------------- 注入渲染 ----------------


def test_context_section_renders_numbered_citations_with_sources():
    answer = knowledge.KnowledgeAnswer(
        query="q",
        answer=None,
        citations=[
            knowledge.KnowledgeCitation("chk_1", "doc_1", "退款政策", 0, 0.9, "购买后\n30 天 可退款。 "),
            knowledge.KnowledgeCitation("chk_2", "doc_2", "品牌规范", 2, None, "品牌主色为深蓝"),
        ],
    )
    lines = knowledge.context_section(answer).splitlines()
    assert lines[0].startswith("业务文档参考")
    assert lines[1] == "[1]《退款政策》购买后 30 天 可退款。"
    assert lines[2] == "[2]《品牌规范》品牌主色为深蓝"


def test_context_section_caps_citation_content():
    answer = knowledge.KnowledgeAnswer(
        query="q",
        answer=None,
        citations=[
            knowledge.KnowledgeCitation(
                "chk_1", "doc_1", "长文档", 0, None, "字" * (knowledge.CITATION_CONTENT_CAP + 50)
            )
        ],
    )
    line = knowledge.context_section(answer).splitlines()[1]
    assert line.endswith("…")
    assert len(line) < len("字" * knowledge.CITATION_CONTENT_CAP) + 20
