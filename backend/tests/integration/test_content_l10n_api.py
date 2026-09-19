"""Q119/Q58 段12 多语言集成测试：语言清单 CRUD/RBAC、语言交集、目标语言收窄、
按语言生成独立成品（422/409/201）。段12 Gate=客户审阅，非运营 Gate。
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.content.models import ContentLanguage
from app.core.db import Base, get_session
from app.core.model_registry.models import AIModel, AISceneRoute, SkillPrompt, SkillPromptVersion
from app.core.model_registry.seeds import (
    ARTICLE_GEN_PROMPT_ID,
    ARTICLE_GEN_PROMPT_TEMPLATE,
    ARTICLE_GEN_PROMPT_VARIABLES,
    ARTICLE_GEN_PROMPT_VERSION,
    ARTICLE_QC_PROMPT_ID,
    ARTICLE_QC_PROMPT_TEMPLATE,
    ARTICLE_QC_PROMPT_VARIABLES,
    ARTICLE_QC_PROMPT_VERSION,
    ARTICLE_SEMANTIC_PROMPT_ID,
    ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
    ARTICLE_SEMANTIC_PROMPT_VARIABLES,
    ARTICLE_SEMANTIC_PROMPT_VERSION,
    SCENE_ARTICLE_GEN,
    SCENE_ARTICLE_QC,
    SCENE_ARTICLE_SEMANTIC,
    SYNTHETIC_MODEL_ID,
)
from app.final.final_whitelist.models import FinalContentWhitelist
from app.main import app
from app.product.product_intake.models import ProductSpace

DICT = {"id": "u-dict", "roles": ["dictionary_admin"]}
OPS = {"id": "u-ops", "roles": ["operations"]}
CUSTOMER = {"id": "u-cust", "roles": ["whitelist_owner"]}



def _fcw(final_id: str, platform: str, slot_id: str, country, goal: str) -> FinalContentWhitelist:
    return FinalContentWhitelist(
        final_id=final_id,
        tenant_id="t1",
        product_space_id="ps-1",
        pws_id=f"pws-{final_id}",
        pwc_id="pwc-1",
        pcp_id="pcp-1",
        csp_package_id="csp-1",
        cstp_package_id="cstp-1",
        cep_package_id="cep-1",
        platform=platform,
        slot_id=slot_id,
        goal=goal,
        country=country,
        guards_passed=True,
        issued_by="ops-1",
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        session.add_all([
            AIModel(
                model_id=SYNTHETIC_MODEL_ID, model_code="synthetic-deterministic",
                provider="synthetic", status="active",
            ),
            AISceneRoute(scene=SCENE_ARTICLE_GEN, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_GEN, current_version=ARTICLE_GEN_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_GEN_PROMPT_ID, skill_id=SCENE_ARTICLE_GEN,
                version=ARTICLE_GEN_PROMPT_VERSION, template=ARTICLE_GEN_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_GEN_PROMPT_VARIABLES},
            ),
            AISceneRoute(scene=SCENE_ARTICLE_QC, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_QC, current_version=ARTICLE_QC_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_QC_PROMPT_ID, skill_id=SCENE_ARTICLE_QC,
                version=ARTICLE_QC_PROMPT_VERSION, template=ARTICLE_QC_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_QC_PROMPT_VARIABLES},
            ),
            AISceneRoute(scene=SCENE_ARTICLE_SEMANTIC, model_id=SYNTHETIC_MODEL_ID),
            SkillPrompt(skill_id=SCENE_ARTICLE_SEMANTIC, current_version=ARTICLE_SEMANTIC_PROMPT_VERSION),
            SkillPromptVersion(
                version_id=ARTICLE_SEMANTIC_PROMPT_ID, skill_id=SCENE_ARTICLE_SEMANTIC,
                version=ARTICLE_SEMANTIC_PROMPT_VERSION, template=ARTICLE_SEMANTIC_PROMPT_TEMPLATE,
                variables={"vars": ARTICLE_SEMANTIC_PROMPT_VARIABLES},
            ),
            # Q119：zh-CN markets=[] 覆盖全市场（迁移种子口径）。
            ContentLanguage(code="zh-CN", name="简体中文", markets=[], status="active"),
            ProductSpace(
                product_space_id="ps-1", tenant_id="t1", intake_id="int-1"
            ),
            _fcw("fcw-1", "douyin", "slot-1", None, "awareness"),
            _fcw("fcw-us", "amazon", "slot-us", "US", "conversion"),
        ])
        await session.commit()

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


def _gen_body(final_id: str, language: str | None = None) -> dict:
    fcw = "fcw-us" if final_id == "fcw-us" else "fcw-1"
    platform = "amazon" if fcw == "fcw-us" else "douyin"
    slot = "slot-us" if fcw == "fcw-us" else "slot-1"
    country = "US" if fcw == "fcw-us" else None
    body = {
        "actor": OPS,
        "final_id": final_id,
        "kind": "article",
        "goal": "conversion" if fcw == "fcw-us" else "awareness",
        "platform": platform,
        "slot_id": slot,
        "country": country,
    }
    if language is not None:
        body["language"] = language
    return body


# ---- 语言清单 CRUD / RBAC ----

async def test_list_languages_requires_query_actor(client):
    r = await client.get("/api/admin/content-languages")
    assert r.status_code == 422


async def test_list_languages_forbids_non_dictionary_admin(client):
    r = await client.get(
        "/api/admin/content-languages", params={"actor_id": "u-ops", "roles": "operations"}
    )
    assert r.status_code == 403


async def test_language_crud_dict_admin(client):
    r = await client.get(
        "/api/admin/content-languages",
        params={"actor_id": "u-dict", "roles": "dictionary_admin"},
    )
    assert r.status_code == 200
    assert [row["code"] for row in r.json()] == ["zh-CN"]

    # operations 不能写（字典维护归 dictionary_admin）
    r = await client.put(
        "/api/admin/content-languages",
        json={"actor": OPS, "code": "en-US", "name": "English", "markets": ["US"]},
    )
    assert r.status_code == 403

    # 空 name → 422
    r = await client.put(
        "/api/admin/content-languages",
        json={"actor": DICT, "code": "en-US", "name": "", "markets": ["US"]},
    )
    assert r.status_code == 422

    # 正常新建
    r = await client.put(
        "/api/admin/content-languages",
        json={"actor": DICT, "code": "en-US", "name": "English (US)", "markets": ["US"]},
    )
    assert r.status_code == 200
    assert r.json()["markets"] == ["US"]

    # 归档 + 404
    r = await client.post(
        "/api/admin/content-languages/en-US/archive", json={"actor": DICT}
    )
    assert r.status_code == 200
    r = await client.post(
        "/api/admin/content-languages/fr-FR/archive", json={"actor": DICT}
    )
    assert r.status_code == 404

    # upsert 复活归档语言
    r = await client.put(
        "/api/admin/content-languages",
        json={"actor": DICT, "code": "en-US", "name": "English (US)", "markets": ["US"]},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"


# ---- 语言交集 ----

async def test_eligible_query_gate_and_intersection(client):
    # 缺 actor 422 / customer 403 / ghost final 404
    assert (await client.get("/api/content/eligible-languages", params={"final_id": "fcw-1"})).status_code == 422
    assert (await client.get("/api/content/eligible-languages", params={"final_id": "fcw-1", "actor_id": "u-cust", "roles": "whitelist_owner"})).status_code == 403
    assert (await client.get("/api/content/eligible-languages", params={"final_id": "ghost", "actor_id": "u-ops", "roles": "operations"})).status_code == 404

    # 仅 zh-CN：通用发布位（country None）与美国发布位都可用 zh-CN
    r = await client.get(
        "/api/content/eligible-languages",
        params={"final_id": "fcw-1", "actor_id": "u-ops", "roles": "operations"},
    )
    assert r.json()["eligible"] == ["zh-CN"]
    r = await client.get(
        "/api/content/eligible-languages",
        params={"final_id": "fcw-us", "actor_id": "u-ops", "roles": "operations"},
    )
    assert r.json()["eligible"] == ["zh-CN"]

    # 加 en-US 仅美国
    await client.put(
        "/api/admin/content-languages",
        json={"actor": DICT, "code": "en-US", "name": "English (US)", "markets": ["US"]},
    )
    r = await client.get(
        "/api/content/eligible-languages",
        params={"final_id": "fcw-us", "actor_id": "u-ops", "roles": "operations"},
    )
    # code 字典序 en-US 在前
    assert r.json()["eligible"] == ["en-US", "zh-CN"]
    # 通用发布位（country None）不含受限的 en-US
    r = await client.get(
        "/api/content/eligible-languages",
        params={"final_id": "fcw-1", "actor_id": "u-ops", "roles": "operations"},
    )
    assert r.json()["eligible"] == ["zh-CN"]


async def test_product_target_languages_narrows_and_rbac(client):
    await client.put(
        "/api/admin/content-languages",
        json={"actor": DICT, "code": "en-US", "name": "English (US)", "markets": ["US"]},
    )
    url = "/api/product-spaces/ps-1/target-languages"
    # customer 403
    assert (await client.put(url, json={"actor": CUSTOMER, "languages": ["en-US"]})).status_code == 403
    # 重复语言 422
    assert (await client.put(url, json={"actor": OPS, "languages": ["en-US", "en-US"]})).status_code == 422
    # ghost ps 404
    assert (await client.put("/api/product-spaces/ghost/target-languages", json={"actor": OPS, "languages": ["en-US"]})).status_code == 404

    r = await client.put(url, json={"actor": OPS, "languages": ["en-US"]})
    assert r.status_code == 200
    assert r.json()["target_languages"] == ["en-US"]

    r = await client.get(
        "/api/content/eligible-languages",
        params={"final_id": "fcw-us", "actor_id": "u-ops", "roles": "operations"},
    )
    # 产品侧收窄到 en-US（zh-CN 被排除）
    assert r.json()["eligible"] == ["en-US"]

    # 清空 = 未声明/不限
    r = await client.put(url, json={"actor": OPS, "languages": []})
    assert r.status_code == 200
    assert r.json()["target_languages"] is None


# ---- 按语言生成独立成品 ----

async def test_generate_language_eligibility_duplicate_independence(client):
    # en-US 尚未配置 → 422
    r = await client.post("/api/content/generate", json=_gen_body("fcw-1", "en-US"))
    assert r.status_code == 422

    await client.put(
        "/api/admin/content-languages",
        json={"actor": DICT, "code": "en-US", "name": "English (US)", "markets": ["US"]},
    )
    # en-US 仅覆盖 US，通用发布位 fcw-1（country None）仍 422
    r = await client.post("/api/content/generate", json=_gen_body("fcw-1", "en-US"))
    assert r.status_code == 422

    # fcw-us 可生成英文独立成品
    r = await client.post("/api/content/generate", json=_gen_body("fcw-us", "en-US"))
    assert r.status_code == 201
    en = r.json()
    assert en["language"] == "en-US"
    assert "language=en-US" in en["body"]

    # 同 final+lang+kind 重复 → 409
    r = await client.post("/api/content/generate", json=_gen_body("fcw-us", "en-US"))
    assert r.status_code == 409

    # 同一 final 的 zh-CN 是另一条独立成品
    r = await client.post("/api/content/generate", json=_gen_body("fcw-us", "zh-CN"))
    assert r.status_code == 201
    assert r.json()["content_id"] != en["content_id"]
    assert r.json()["language"] == "zh-CN"

    # 不传 language 默认 zh-CN，向后兼容
    r = await client.post("/api/content/generate", json=_gen_body("fcw-1"))
    assert r.status_code == 201
    assert r.json()["language"] == "zh-CN"
