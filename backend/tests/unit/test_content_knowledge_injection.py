"""ARTICLE-GEN 知识库上下文注入消费点单测（M3-W3-5）。

覆盖消费点 ``generation._knowledge_section`` 的四种形态：
- 命中：query_knowledge 返回命中 ⇒ 渲染出带出处的参考段；
- 无命中 / 停用（env 缺失）：消费点拿到 None ⇒ 不注入；
- 异常：query_knowledge 抛错 ⇒ 消费点兜底吞掉（fail-soft，绝不阻断生成）。
检索词拼装与 _materials_text 的追加行为一并锁定。
"""

from app.content import generation
from app.core import knowledge


def _materials() -> dict:
    return {
        "final_id": "fcw-1",
        "goal": "种草",
        "platform": "douyin",
        "country": "CN",
        "atoms": [{"content": "产品原子甲"}, {"content": "产品原子乙"}],
        "packages": {},
        "weights": {},
        "ccr_hits": {},
    }


def _fake_answer(query: str) -> knowledge.KnowledgeAnswer:
    return knowledge.KnowledgeAnswer(
        query=query,
        answer="退款窗口 30 天 [1]。",
        citations=[
            knowledge.KnowledgeCitation("chk_1", "doc_1", "退款政策", 0, 0.9, "购买后 30 天可退款。")
        ],
    )


# ---------------- 检索词拼装 ----------------


def test_knowledge_query_text_builds_goal_platform_atoms():
    query = generation._knowledge_query_text(_materials())
    assert query == "种草 douyin 产品原子甲 产品原子乙"


def test_knowledge_query_text_caps_atom_text():
    materials = _materials()
    materials["atoms"] = [{"content": "字" * (knowledge.QUERY_ATOM_CHARS + 100)}]
    query = generation._knowledge_query_text(materials)
    assert query == "种草 douyin " + "字" * knowledge.QUERY_ATOM_CHARS


def test_knowledge_query_text_empty_without_usable_materials():
    assert generation._knowledge_query_text({"goal": "", "platform": "", "atoms": []}) == ""
    # 非 dict 的原子条目跳过，不炸。
    assert generation._knowledge_query_text({"goal": "g", "platform": "", "atoms": ["str"]}) == "g"


# ---------------- 原料文本追加 ----------------


def test_materials_text_appends_knowledge_section():
    base = generation._materials_text(_materials())
    extended = generation._materials_text(_materials(), "业务文档参考\n[1]《退款政策》30 天")
    assert extended.startswith(base)
    assert extended.endswith("[1]《退款政策》30 天")
    assert "业务文档参考" not in base  # 缺省 None ⇒ 与既有形态逐字节一致


# ---------------- 消费点四面 ----------------


async def test_knowledge_section_hit(monkeypatch):
    async def fake_query(query, **kwargs):
        return _fake_answer(query)

    monkeypatch.setattr(knowledge, "query_knowledge", fake_query)
    section = await generation._knowledge_section(_materials())
    assert section is not None
    assert "[1]《退款政策》购买后 30 天可退款。" in section


async def test_knowledge_section_no_hit_skips(monkeypatch):
    async def fake_query(query, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "query_knowledge", fake_query)
    assert await generation._knowledge_section(_materials()) is None


async def test_knowledge_section_disabled_skips(monkeypatch):
    # env 缺失 ⇒ 真 query_knowledge fail-closed 直接 None（不发请求）。
    monkeypatch.delenv("LOOM_KNOWLEDGE_URL", raising=False)
    monkeypatch.delenv("LOOM_KNOWLEDGE_TOKEN", raising=False)
    assert await generation._knowledge_section(_materials()) is None


async def test_knowledge_section_empty_query_skips(monkeypatch):
    async def fake_query(query, **kwargs):  # pragma: no cover - 不应到达
        raise AssertionError("empty query must not reach query_knowledge")

    monkeypatch.setattr(knowledge, "query_knowledge", fake_query)
    assert await generation._knowledge_section({"goal": "", "platform": "", "atoms": []}) is None


async def test_knowledge_section_error_fail_soft(monkeypatch):
    async def boom(query, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(knowledge, "query_knowledge", boom)
    assert await generation._knowledge_section(_materials()) is None
