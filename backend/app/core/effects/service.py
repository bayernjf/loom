"""段13 效果回流接收/时序/孤儿分流/人工认领/客户回填/认领解绑服务（Q126–Q129）。

契约：05 §1.1.1 / 11 §2.1（Q60/Q60a）。

数据纪律（硬性）：
- metrics 缺席=未采集，键不落库（NULL/省略），绝不当 0、不许估算。
- 幂等：同 content_id + captured_at 幂等覆盖；同 content_id 不同 captured_at 追加时序。
- 孤儿：推送的 content_id 对不上本系统有效成品（含已 discarded）进 orphan 队列。
- 整批 all-or-nothing：任一记录非法即 422，不写部分数据（同 Q93 口径）。

两条入站通道：
- Agent 通道 POST /api/effect-callback（Q126，Bearer Agent Key）：全局匹配，
  对不上进孤儿；自动匹配失败再查 Q127 人工认领映射兜底。
- 客户通道 POST /api/effects/backfill（Q128，body actor + tenant_id）：source
  服务端固定 customer-backfill，只接受本租户非 discarded 成品，绝不产生孤儿。

本切片不含：效果反哺/评分校准算法（口径原文未给，标【待补】），随段13 后续片/V2。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.models import CONTENT_DISCARDED, ContentProduct
from app.core.actor import Actor
from app.core.api_keys.models import AgentApiKey
from app.core.api_keys.service import PLATFORM_TENANT
from app.core.audit import append_audit
from app.core.effects.models import (
    METRIC_COUNTERS,
    METRIC_KEYS,
    METRIC_RATE_KEYS,
    STATUS_MATCHED,
    STATUS_ORPHAN,
    EffectClaim,
    EffectRecord,
)
from app.core.effects.schemas import (
    CustomerEffectBatchIn,
    EffectBatchIn,
    EffectRecordIn,
)
from app.core.rbac import OPERATIONS, require_any_role


class EffectValidationError(Exception):
    """整批中第 index 条（0 基）记录的字段非法；调用方回 422。"""

    def __init__(self, index: int, field: str, message: str) -> None:
        self.index = index
        self.field = field
        super().__init__(message)


# ---------- Q127/Q60a 人工认领异常（调用方映射 404/409） ----------


class ClaimError(Exception):
    """人工认领动作的业务拒绝基类。"""


class ClaimRecordNotFound(ClaimError):
    """孤儿记录不存在。"""


class ClaimRecordNotOrphan(ClaimError):
    """入口记录已不是孤儿（已自动匹配或已认领）。"""


class ClaimTargetNotFound(ClaimError):
    """绑定目标成品不存在。"""


class ClaimTargetDiscarded(ClaimError):
    """绑定目标成品已 discarded（终态，不可绑定）。"""


class ClaimMappingNotFound(ClaimError):
    """解绑（Q129）时认领映射不存在。"""


def _is_real_number(value: object) -> bool:
    """计数/比率须为数值；bool 是 int 子类，显式排除。"""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_metrics(index: int, raw: object) -> dict | None:
    """校验并稀疏化 metrics：缺席/None 不落，未知键与非法类型 422。

    计数六键须为非负整数；read_rate 须为 0..1 数值；其余未知键一律拒绝。
    """

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise EffectValidationError(index, "metrics", "metrics must be an object")

    normalized: dict[str, object] = {}
    for key, value in raw.items():
        if key not in METRIC_KEYS:
            raise EffectValidationError(index, f"metrics.{key}", "unknown metric key")
        if value is None:
            # 显式 null 等同未采集，省略该键（绝不写 0）。
            continue
        if key in METRIC_COUNTERS and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise EffectValidationError(
                index, f"metrics.{key}", "counter must be a non-negative integer"
            )
        # METRIC_COUNTERS 与 METRIC_RATE_KEYS 互斥，两个独立 if 等价于互斥分支。
        if key in METRIC_RATE_KEYS and (
            not _is_real_number(value) or not 0 <= float(value) <= 1
        ):
            raise EffectValidationError(
                index, f"metrics.{key}", "rate must be a number in [0, 1]"
            )
        normalized[key] = value
    return normalized or None


def _as_utc(dt: datetime) -> datetime:
    """aware datetime 归一到 UTC；sqlite 读回的 naive 值视为 UTC。"""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def validate_record(
    index: int, rec: EffectRecordIn
) -> tuple[str, str, datetime, dict | None]:
    """校验单条记录（不碰库），返回归一四元组；captured_at 须带时区。"""

    content_id = rec.content_id.strip()
    if not content_id:
        raise EffectValidationError(index, "content_id", "content_id is required")
    platform_post_id = rec.platform_post_id.strip()
    if not platform_post_id:
        raise EffectValidationError(
            index, "platform_post_id", "platform_post_id is required"
        )
    if rec.captured_at.tzinfo is None:
        raise EffectValidationError(
            index, "captured_at", "captured_at must include a timezone"
        )
    captured_at = _as_utc(rec.captured_at)
    metrics = normalize_metrics(index, rec.metrics)
    return content_id, platform_post_id, captured_at, metrics


def _normalize_records(
    records: list[EffectRecordIn],
) -> list[tuple[str, str, datetime, dict | None]]:
    """逐条校验/归一 + 批内幂等键去重（不写库）。"""

    normalized: list[tuple[str, str, datetime, dict | None]] = []
    seen: set[tuple[str, datetime]] = set()
    for index, rec in enumerate(records):
        content_id, post_id, captured_at, metrics = validate_record(index, rec)
        dedup_key = (content_id, captured_at)
        if dedup_key in seen:
            raise EffectValidationError(
                index, "captured_at", "duplicate content_id + captured_at within batch"
            )
        seen.add(dedup_key)
        normalized.append((content_id, post_id, captured_at, metrics))
    return normalized


async def _resolve_contents(
    session: AsyncSession, external_ids: set[str], *, tenant_id: str | None = None
) -> dict[str, ContentProduct]:
    """按 content_id 解析本系统有效成品（discarded 不作为命中目标）。

    tenant_id 非空时限本租户（Q128 客户通道）；None 为全局（Agent 通道）。
    """

    stmt = select(ContentProduct).where(ContentProduct.content_id.in_(external_ids))
    if tenant_id is not None:
        stmt = stmt.where(ContentProduct.tenant_id == tenant_id)
    rows = (await session.scalars(stmt)).all()
    return {
        row.content_id: row for row in rows if row.status != CONTENT_DISCARDED
    }


async def _apply_claim_fallback(
    session: AsyncSession,
    content_map: dict[str, ContentProduct],
    external_ids: set[str],
) -> None:
    """Q127/Q60a：自动未命中的 ID 查人工认领映射兜底（就地补 content_map）。

    映射目标成品须存在且非 discarded；目标缺失/已 discarded 不绑定（回落孤儿，
    映射保留）。客户通道不走此兜底（直报必须命中本租户成品）。
    """

    missing = [cid for cid in external_ids if cid not in content_map]
    if not missing:
        return
    claim_rows = (
        await session.scalars(
            select(EffectClaim).where(EffectClaim.external_content_id.in_(missing))
        )
    ).all()
    if not claim_rows:
        return
    target_map = await _resolve_contents(
        session, {claim.content_id for claim in claim_rows}
    )
    for claim in claim_rows:
        target = target_map.get(claim.content_id)
        if target is not None:
            content_map[claim.external_content_id] = target


async def _persist_records(
    session: AsyncSession,
    *,
    source: str,
    normalized: list[tuple[str, str, datetime, dict | None]],
    content_map: dict[str, ContentProduct],
    received_by: str | None,
    now: datetime,
) -> dict[str, int]:
    """按幂等/时序口径落库（不写审计），返回 {received,matched,orphan,upserted}。"""

    external_ids = {item[0] for item in normalized}

    # 一次性取这批涉及的既有记录，按幂等键建索引（captured_at 统一 UTC 比较）。
    existing_rows = (
        await session.scalars(
            select(EffectRecord).where(
                EffectRecord.external_content_id.in_(external_ids)
            )
        )
    ).all()
    existing_map = {
        (row.external_content_id, _as_utc(row.captured_at)): row
        for row in existing_rows
    }

    matched = orphan = upserted = 0
    for content_id, post_id, captured_at, metrics in normalized:
        content = content_map.get(content_id)
        row = existing_map.get((content_id, captured_at))
        if row is not None:
            # 幂等覆盖（Q60）：刷新来源/帖子/指标，重算匹配，不新增行。
            # Q127：content_map 已含认领映射兜底，人工认领过的 ID 不会在此冲回 orphan。
            row.source = source
            row.platform_post_id = post_id
            row.metrics = metrics
            if content is not None:
                row.matched_content_id = content.content_id
                row.tenant_id = content.tenant_id
                row.status = STATUS_MATCHED
            else:
                row.matched_content_id = None
                row.tenant_id = None
                row.status = STATUS_ORPHAN
            row.received_by = received_by
            row.updated_at = now
            upserted += 1
        else:
            if content is not None:
                matched_content_id = content.content_id
                tenant_id = content.tenant_id
                status = STATUS_MATCHED
            else:
                matched_content_id = None
                tenant_id = None
                status = STATUS_ORPHAN
            session.add(
                EffectRecord(
                    source=source,
                    external_content_id=content_id,
                    matched_content_id=matched_content_id,
                    tenant_id=tenant_id,
                    platform_post_id=post_id,
                    captured_at=captured_at,
                    metrics=metrics,
                    status=status,
                    received_by=received_by,
                )
            )
        if content is not None:
            matched += 1
        else:
            orphan += 1

    return {
        "received": len(normalized),
        "matched": matched,
        "orphan": orphan,
        "upserted": upserted,
    }


async def ingest_effects(
    session: AsyncSession,
    *,
    batch: EffectBatchIn,
    key: AgentApiKey,
) -> dict[str, int]:
    """Agent 通道整批接收（all-or-nothing），返回 {received,matched,orphan,upserted}。"""

    source = batch.source.strip()
    if not source:
        # pydantic min_length=1 已挡空串，这里防纯空白。
        raise EffectValidationError(-1, "source", "source is required")

    normalized = _normalize_records(batch.records)
    external_ids = {item[0] for item in normalized}

    # 自动匹配（全局、非 discarded）+ Q127 人工认领映射兜底。
    content_map = await _resolve_contents(session, external_ids)
    await _apply_claim_fallback(session, content_map, external_ids)

    receipt = await _persist_records(
        session,
        source=source,
        normalized=normalized,
        content_map=content_map,
        received_by=key.key_id,
        now=datetime.now(UTC),
    )

    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=key.key_id,
        actor_roles=[],
        action="effect.batch_received",
        entity_type="effect_batch",
        entity_id=str(uuid.uuid4()),
        detail={"source": source, **receipt},
    )
    return receipt


async def ingest_customer_backfill(
    session: AsyncSession,
    *,
    batch: CustomerEffectBatchIn,
) -> dict[str, int]:
    """Q128 客户通道整批回填（all-or-nothing）。

    source 服务端固定 customer-backfill；每条 content_id 必须命中本租户非
    discarded 成品，否则该条 422（客户通道绝不产生孤儿）。
    """

    tenant_id = batch.tenant_id.strip()
    if not tenant_id:
        raise EffectValidationError(-1, "tenant_id", "tenant_id is required")

    normalized = _normalize_records(batch.records)
    external_ids = {item[0] for item in normalized}

    # 客户通道只在本租户内匹配，且不走认领映射兜底。
    content_map = await _resolve_contents(
        session, external_ids, tenant_id=tenant_id
    )
    for index, (content_id, _post_id, _ts, _metrics) in enumerate(normalized):
        if content_id not in content_map:
            raise EffectValidationError(
                index,
                "content_id",
                "content_id not found for this tenant or content discarded",
            )

    receipt = await _persist_records(
        session,
        source="customer-backfill",
        normalized=normalized,
        content_map=content_map,
        received_by=batch.actor.id,
        now=datetime.now(UTC),
    )
    # 全部命中本租户成品，孤儿计数必为 0；防御性断言防后续重构破坏口径。
    if receipt["orphan"]:  # pragma: no cover - 口径不变即不可达
        raise RuntimeError("customer backfill must never produce orphans")

    await append_audit(
        session,
        tenant_id=tenant_id,
        actor_id=batch.actor.id,
        actor_roles=list(batch.actor.roles),
        action="effect.customer_backfilled",
        entity_type="effect_batch",
        entity_id=str(uuid.uuid4()),
        detail=receipt,
    )
    return receipt


async def _claim_one(
    session: AsyncSession,
    *,
    record_id: str,
    content_id: str,
    actor: Actor,
) -> dict[str, object]:
    """单条认领落库（不做角色闸，由调用方统一闸）：校验 + upsert 映射 + 回填行 + 审计。"""

    record = await session.get(EffectRecord, record_id)
    if record is None:
        raise ClaimRecordNotFound(f"effect record {record_id} not found")
    if record.status != STATUS_ORPHAN:
        raise ClaimRecordNotOrphan(
            f"effect record {record_id} is not orphan (current {record.status})"
        )

    target = await session.get(ContentProduct, content_id)
    if target is None:
        raise ClaimTargetNotFound(f"content {content_id} not found")
    if target.status == CONTENT_DISCARDED:
        raise ClaimTargetDiscarded(f"content {content_id} is discarded")

    external_id = record.external_content_id
    now = datetime.now(UTC)

    claim = await session.get(EffectClaim, external_id)
    if claim is None:
        session.add(
            EffectClaim(
                external_content_id=external_id,
                content_id=target.content_id,
                claimed_by=actor.id,
                claimed_at=now,
            )
        )
    else:
        # 改绑：覆盖目标与认领人（旧目标被 discarded 后重新认领也走这里）。
        claim.content_id = target.content_id
        claim.claimed_by = actor.id
        claim.claimed_at = now
        claim.updated_at = now

    rows = (
        await session.scalars(
            select(EffectRecord).where(
                EffectRecord.external_content_id == external_id,
                or_(
                    EffectRecord.status == STATUS_ORPHAN,
                    EffectRecord.claimed_by.is_not(None),
                ),
            )
        )
    ).all()
    updated_rows = 0
    for row in rows:
        row.matched_content_id = target.content_id
        row.tenant_id = target.tenant_id
        row.status = STATUS_MATCHED
        row.claimed_by = actor.id
        row.claimed_at = now
        row.updated_at = now
        updated_rows += 1

    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=list(actor.roles),
        action="effect.claimed",
        entity_type="effect_claim",
        entity_id=external_id,
        detail={
            "external_content_id": external_id,
            "content_id": target.content_id,
            "updated_rows": updated_rows,
        },
    )

    return {
        "external_content_id": external_id,
        "content_id": target.content_id,
        "claimed_by": actor.id,
        "claimed_at": now,
        "updated_rows": updated_rows,
    }


async def claim_orphan(
    session: AsyncSession,
    *,
    record_id: str,
    content_id: str,
    actor: Actor,
) -> dict[str, object]:
    """Q127/Q60a：运营把一条孤儿记录人工绑定到本系统成品。

    - 入口记录须存在且当前为 orphan（404/409）；目标成品须存在且非 discarded（404/409）。
    - upsert external_content_id→content_id 持久映射（重复认领=改绑）；该 ID
      之后的推送（覆盖/新采集点）按映射自动 matched，不回落孤儿。
    - 回填该 external_content_id 下全部 orphan 行与历史人工认领行（改绑重指）；
      自动 matched 行不动。
    """

    require_any_role(actor, OPERATIONS)
    return await _claim_one(
        session, record_id=record_id, content_id=content_id, actor=actor
    )


async def claim_orphan_batch(
    session: AsyncSession,
    *,
    items: list,
    actor: Actor,
) -> dict[str, int]:
    """Q129：批量人工认领，整批 all-or-nothing（同 Q93/Q126 口径）。

    任一条 404/409 或批内 record_id 重复，整批拒（router 回滚，不落半批）；
    逐条 effect.claimed 审计随事务一起提交或回滚。
    """

    require_any_role(actor, OPERATIONS)
    seen: set[str] = set()
    for index, item in enumerate(items):
        if item.record_id in seen:
            raise EffectValidationError(
                index, "record_id", "duplicate record_id within batch"
            )
        seen.add(item.record_id)

    total_updated = 0
    for item in items:
        result = await _claim_one(
            session,
            record_id=item.record_id,
            content_id=item.content_id,
            actor=actor,
        )
        total_updated += int(result["updated_rows"])
    return {"claimed": len(items), "updated_rows": total_updated}


async def unclaim_orphan(
    session: AsyncSession,
    *,
    external_content_id: str,
    actor: Actor,
) -> dict[str, object]:
    """Q129：取消认领/解绑（Q127 挂账）。

    - 删除 external_content_id→content_id 持久映射（映射不存在 404）；
    - 该 ID 下因该映射而 matched 到旧目标的行一律回滚为 orphan
      （清空 matched_content_id/tenant_id/claimed_by/claimed_at）——含人工认领
      回填行与认领后经兜底匹配的新推送行；external_id 自匹配的真自动 matched 行
      （matched_content_id==external_content_id）不可能指向映射目标，天然不受影响；
    - 解绑后同 ID 的后续推送不再走认领兜底，重新按自动匹配分流；
    - 审计 effect.claim_revoked（tenant _platform、entity_id=external_content_id）。
    """

    require_any_role(actor, OPERATIONS)

    claim = await session.get(EffectClaim, external_content_id)
    if claim is None:
        raise ClaimMappingNotFound(f"effect claim {external_content_id} not found")
    old_content_id = claim.content_id
    await session.delete(claim)

    rows = (
        await session.scalars(
            select(EffectRecord).where(
                EffectRecord.external_content_id == external_content_id,
                EffectRecord.matched_content_id == old_content_id,
            )
        )
    ).all()
    now = datetime.now(UTC)
    reverted_rows = 0
    for row in rows:
        row.matched_content_id = None
        row.tenant_id = None
        row.status = STATUS_ORPHAN
        row.claimed_by = None
        row.claimed_at = None
        row.updated_at = now
        reverted_rows += 1

    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=list(actor.roles),
        action="effect.claim_revoked",
        entity_type="effect_claim",
        entity_id=external_content_id,
        detail={
            "external_content_id": external_content_id,
            "content_id": old_content_id,
            "reverted_rows": reverted_rows,
        },
    )

    return {
        "external_content_id": external_content_id,
        "reverted_rows": reverted_rows,
    }


async def list_orphans(
    session: AsyncSession, *, limit: int, offset: int
) -> list[EffectRecord]:
    """孤儿队列：跨租户 status=orphan，按采集时间先到先列。"""

    rows = await session.scalars(
        select(EffectRecord)
        .where(EffectRecord.status == STATUS_ORPHAN)
        .order_by(EffectRecord.captured_at.asc(), EffectRecord.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.all())


async def list_series(
    session: AsyncSession, content_id: str, *, limit: int, offset: int
) -> list[EffectRecord]:
    """某成品的效果时间序列（matched_content_id），captured_at 升序。"""

    rows = await session.scalars(
        select(EffectRecord)
        .where(EffectRecord.matched_content_id == content_id)
        .order_by(EffectRecord.captured_at.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.all())


def effect_view(row: EffectRecord) -> dict:
    return {
        "record_id": row.record_id,
        "source": row.source,
        "content_id": row.external_content_id,
        "matched_content_id": row.matched_content_id,
        "tenant_id": row.tenant_id,
        "platform_post_id": row.platform_post_id,
        "captured_at": row.captured_at,
        "metrics": row.metrics,
        "status": row.status,
        "claimed_by": row.claimed_by,
        "claimed_at": row.claimed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
