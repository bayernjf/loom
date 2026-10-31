"""统一错误响应契约（Tier0 评审 2026-10-30 H2）：router 层 5xx 逐点不回显。

每个改动的 ``except`` → 5xx 映射点用直调路由函数的方式断言：状态码不变、
detail 固定泛化、异常原文不出现在响应体，且原文进了服务端日志。带错误码的
业务错误（4xx 语义化 detail）不在本用例面内。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.content.video_studio import router as video_router
from app.content.video_studio.router import stream_video_object, upload_video_object
from app.core.actor import Actor
from app.core.content_base import service as cb_service
from app.core.content_base.errors import ContentBackendUnavailable, ContentBaseError
from app.core.content_base.router import create_request, review
from app.core.content_base.schemas import CreateContentRequest, ReviewContentRequest
from app.core.model_registry import c7_resolve, extraction, field_plan, gateway, hub
from app.core.model_registry.router import hub_sync, invoke_c1_recognition, invoke_c7_resolve
from app.core.model_registry.schemas import (
    AtomExpandInvokeRequest,
    C7ResolveInvokeRequest,
    FieldPlanInvokeRequest,
    RecognizeInvokeRequest,
)
from app.core.skill7 import service as s7_service
from app.core.skill7.router import suggest_ai_select
from app.core.skill7.schemas import AiSelectSuggestRequest
from app.product.atom import service as atom_service
from app.product.atom.router import ai_supplement_evidence, llm_expand
from app.product.atom.schemas import LifecycleRequest
from app.product.condition.router import llm_build
from app.product.condition.schemas import ActorRequest
from app.product.fieldpool.router import llm_plan

LEAK = "ECONNREFUSED 10.0.0.5:5432 — relation targets leaked"

OPS = Actor(id="ops-1", roles=["operations"])


async def _expect_no_echo(caplog, coro, status: int, detail: str) -> None:
    with caplog.at_level("WARNING", logger="loom.errors"), pytest.raises(HTTPException) as ei:
        await coro
    assert ei.value.status_code == status
    assert ei.value.detail == detail
    assert LEAK not in repr(ei.value.detail)
    assert LEAK in caplog.text


async def test_content_base_backend_unavailable_503(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise ContentBackendUnavailable(LEAK)

    monkeypatch.setattr(cb_service, "submit_candidate", _boom)
    body = CreateContentRequest(product_id="p1", channel="web", content_type="detail", actor=OPS)
    await _expect_no_echo(
        caplog, create_request(body=body, session=AsyncMock()), 503, "content backend unavailable"
    )


async def test_content_base_unknown_base_error_500(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise ContentBaseError(LEAK)

    monkeypatch.setattr(cb_service, "submit_candidate", _boom)
    body = CreateContentRequest(product_id="p1", channel="web", content_type="detail", actor=OPS)
    await _expect_no_echo(
        caplog, create_request(body=body, session=AsyncMock()), 500, "internal error"
    )


async def test_content_base_review_500(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise ContentBaseError(LEAK)

    monkeypatch.setattr(cb_service, "review_candidate", _boom)
    body = ReviewContentRequest(decision="confirmed", actor=OPS)
    await _expect_no_echo(
        caplog, review(candidate_id="c1", body=body, session=AsyncMock()), 500, "internal error"
    )


async def test_hub_sync_502_hides_hub_error(caplog, monkeypatch):
    def _boom():
        raise RuntimeError(LEAK)

    monkeypatch.setattr(hub, "is_hub_configured", lambda: True)
    monkeypatch.setattr(hub, "sync_hub_projection", _boom)
    await _expect_no_echo(caplog, hub_sync(), 502, "hub sync failed")


async def test_c7_resolve_502_hides_upstream_detail(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise gateway.GenerationUpstreamError(LEAK)

    monkeypatch.setattr(c7_resolve, "invoke_c7_resolve", _boom)
    body = C7ResolveInvokeRequest(category_id="cat-1", actor=OPS)
    await _expect_no_echo(
        caplog,
        invoke_c7_resolve("i1", body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


async def test_c1_recognition_502_hides_upstream_detail(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise gateway.GenerationUpstreamError(LEAK)

    monkeypatch.setattr(extraction, "invoke_c1_recognition", _boom)
    body = RecognizeInvokeRequest(actor=OPS)
    await _expect_no_echo(
        caplog,
        invoke_c1_recognition("i1", body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


async def test_skill7_suggest_502_hides_upstream_detail(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise gateway.GenerationUpstreamError(LEAK)

    monkeypatch.setattr(s7_service, "suggest_ai_select", _boom)
    body = AiSelectSuggestRequest(scene="PT-CONTENT-GOAL-PLAN", product_space_id="ps1", actor=OPS)
    await _expect_no_echo(
        caplog,
        suggest_ai_select(body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


async def test_atom_llm_expand_502_hides_upstream_detail(caplog, monkeypatch):
    from app.core.model_registry import atom_expand

    async def _boom(*a, **kw):
        raise gateway.GenerationUpstreamError(LEAK)

    monkeypatch.setattr(atom_expand, "invoke_atom_expand", _boom)
    body = AtomExpandInvokeRequest(actor=OPS)
    await _expect_no_echo(
        caplog,
        llm_expand(product_space_id="ps1", body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


async def test_atom_ai_supplement_502_hides_pipeline_detail(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise atom_service.AtomEvidenceOutputInvalid(LEAK)

    monkeypatch.setattr(atom_service, "ai_supplement_evidence", _boom)
    body = LifecycleRequest(actor=OPS)
    await _expect_no_echo(
        caplog,
        ai_supplement_evidence(candidate_id="c1", body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


async def test_condition_llm_build_502_hides_upstream_detail(caplog, monkeypatch):
    from app.core.model_registry import pwc_build

    async def _boom(*a, **kw):
        raise gateway.GenerationUpstreamError(LEAK)

    monkeypatch.setattr(pwc_build, "invoke_pwc_build", _boom)
    body = ActorRequest(actor=OPS)
    await _expect_no_echo(
        caplog,
        llm_build(product_space_id="ps1", body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


async def test_fieldpool_llm_plan_502_hides_pipeline_detail(caplog, monkeypatch):
    async def _boom(*a, **kw):
        raise field_plan.FieldPlanOutputInvalid(LEAK)

    monkeypatch.setattr(field_plan, "invoke_field_plan", _boom)
    body = FieldPlanInvokeRequest(actor=OPS)
    await _expect_no_echo(
        caplog,
        llm_plan(product_space_id="ps1", body=body, session=AsyncMock()),
        502,
        "upstream model pipeline failed",
    )


def _s3_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "AccessDenied", "Message": LEAK}},
        operation_name="PutObject",
    )


async def test_video_upload_502_hides_bucket_detail(caplog, monkeypatch):
    async def _fake_content(session, content_id):
        return SimpleNamespace(tenant_id="t1")

    class _S3:
        def put_object(self, **kw):
            raise _s3_error()

    monkeypatch.setattr(video_router, "_require_content", _fake_content)
    monkeypatch.setattr(video_router, "_s3_client", lambda: _S3())

    async def _receive():
        return {"type": "http.request", "body": b"bytes", "more_body": False}

    request = video_router.Request(
        {"type": "http", "method": "POST", "headers": [], "query_string": b""}, receive=_receive
    )
    await _expect_no_echo(
        caplog,
        upload_video_object(
            "content-1", request, filename="video.bin", session=AsyncMock(), actor=OPS
        ),
        502,
        "object storage error",
    )


async def test_video_stream_502_hides_bucket_detail(caplog, monkeypatch):
    class _S3:
        def get_object(self, **kw):
            raise _s3_error()

    async def _get_object(session, object_id):
        return SimpleNamespace(
            bucket="internal-bucket", object_key="k.mp4", content_type="video/mp4"
        )

    monkeypatch.setattr(video_router.service, "get_object", _get_object)
    monkeypatch.setattr(video_router, "_s3_client", lambda: _S3())
    await _expect_no_echo(
        caplog,
        stream_video_object(object_id="obj-1", session=AsyncMock()),
        502,
        "object storage error",
    )
