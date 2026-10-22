"""内容底座契约与内存后端单测（M4/T-M4-01，设计 §4.5）。"""

import pytest

from app.core.content_base import (
    BackendNotRegistered,
    ContentBackend,
    ContentCandidateNotFound,
    ContentCandidateNotReviewable,
    ContentConstraints,
    ContentRequest,
    InMemoryContentBackend,
    get_backend,
    get_default,
    register,
    reset,
)
from app.core.content_base.errors import ContentRequestInvalid


def _request(**overrides) -> ContentRequest:
    base = {
        "product_id": "sku-1",
        "channel": "douyin",
        "content_type": "detail",
        "inputs": {"title": "纯棉T恤"},
    }
    base.update(overrides)
    return ContentRequest(**base)


@pytest.fixture
def backend() -> InMemoryContentBackend:
    return InMemoryContentBackend()


def test_memory_backend_satisfies_protocol() -> None:
    assert isinstance(InMemoryContentBackend(), ContentBackend)


async def test_submit_returns_pending_review_candidate(backend) -> None:
    candidate = await backend.submit(_request())
    assert candidate.status == "pending_review"
    assert candidate.product_id == "sku-1"
    assert candidate.evidence_refs
    assert candidate.final_body is None


async def test_idempotent_key_returns_same_candidate(backend) -> None:
    first = await backend.submit(_request(idempotency_key="key-1"))
    second = await backend.submit(_request(idempotency_key="key-1"))
    assert first.id == second.id


async def test_distinct_requests_get_distinct_candidates(backend) -> None:
    first = await backend.submit(_request())
    second = await backend.submit(_request())
    assert first.id != second.id


async def test_banned_word_in_inputs_is_rejected(backend) -> None:
    request = _request(
        inputs={"title": "全网最有效"},
        constraints=ContentConstraints(banned=["最有效"]),
    )
    with pytest.raises(ContentRequestInvalid):
        await backend.submit(request)


async def test_review_confirmed_freezes_body(backend) -> None:
    candidate = await backend.submit(_request())
    reviewed = await backend.review(candidate.id, "confirmed", reviewer_id="owner-1")
    assert reviewed.status == "confirmed"
    assert reviewed.final_body == reviewed.body
    assert reviewed.reviewed_by == "owner-1"


async def test_review_modified_requires_final_body(backend) -> None:
    candidate = await backend.submit(_request())
    with pytest.raises(ContentRequestInvalid):
        await backend.review(candidate.id, "modified")


async def test_review_modified_uses_replacement_body(backend) -> None:
    candidate = await backend.submit(_request())
    replacement = {"text": "人工改写后的详情"}
    reviewed = await backend.review(candidate.id, "modified", final_body=replacement)
    assert reviewed.status == "modified"
    assert reviewed.final_body == replacement


async def test_review_rejected(backend) -> None:
    candidate = await backend.submit(_request())
    reviewed = await backend.review(candidate.id, "rejected", note="不合规")
    assert reviewed.status == "rejected"
    assert reviewed.final_body is None
    assert reviewed.review_note == "不合规"


async def test_decided_candidate_cannot_be_reviewed_again(backend) -> None:
    candidate = await backend.submit(_request())
    await backend.review(candidate.id, "confirmed")
    with pytest.raises(ContentCandidateNotReviewable):
        await backend.review(candidate.id, "rejected")


async def test_get_missing_candidate_raises(backend) -> None:
    with pytest.raises(ContentCandidateNotFound):
        await backend.get("nope")


def test_registry_returns_registered_backend() -> None:
    reset()
    backend = InMemoryContentBackend()
    register("memory", backend, make_default=True)
    assert get_backend("memory") is backend
    assert get_default() is backend
    reset()


def test_registry_unknown_backend_fails_closed() -> None:
    reset()
    with pytest.raises(BackendNotRegistered):
        get_backend("ghost")
    with pytest.raises(BackendNotRegistered):
        get_default()
