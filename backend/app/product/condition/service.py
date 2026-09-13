"""段5 PWC 条件包服务：Q21 漏斗、Q22 评分、Q23 疑重、Q24 取用/冷却、
Q25 contentGoals 字典、Q26 手拼、Q27 库容、Q71 消费契约。

WF-04 三 Skill（PWC-BUILDER/COMBO-VALIDATE/PWC-SCORING）AI 通道与
Q71 自动补货调度随 M10；M5 接收结构化组合与 AI 分项分做确定性处理。
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.audit import append_audit
from app.core.compliance_wordlist import service as wl_service
from app.product.atom.atom_rules import ATOM_APPROVED
from app.product.atom.models import ProductAtomInstance
from app.product.condition import pwc_rules
from app.product.condition.models import (
    ConditionPackage,
    ContentGoal,
    PwcComboItem,
    PwcPlatformState,
    PwcPoolConfig,
    PwcUsageRecord,
)
from app.product.fieldpool.models import FieldPool
from app.product.product_intake.models import ProductSpace

PLATFORM_TENANT = "_platform"
ROLE_DICT_ADMIN = "dictionary_admin"  # Q25 目的字典入字典管理后台（Q43）


class ProductSpaceNotFound(Exception):
    pass


class PoolNotApproved(Exception):
    pass


class InvalidFunnel(Exception):
    pass


class PwcNotFound(Exception):
    pass


class GateNotAllowed(Exception):
    pass


class CapacityFull(Exception):
    pass


class PoolEmpty(Exception):
    pass


class GoalNotFound(Exception):
    pass


class GoalInvalid(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime | None) -> datetime | None:
    # SQLite 不保留 tzinfo；读回的 naive 值按 UTC 解释（PG 侧本就带时区）。
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ---------- Q25 contentGoals 字典 ----------

async def list_goals(session, *, include_archived: bool = False) -> Sequence[ContentGoal]:
    stmt = select(ContentGoal).order_by(ContentGoal.code)
    if not include_archived:
        stmt = stmt.where(ContentGoal.status == "active")
    return (await session.scalars(stmt)).all()


async def upsert_goal(session, body, actor) -> ContentGoal:
    if ROLE_DICT_ADMIN not in actor.roles:
        raise GateNotAllowed("contentGoals edit requires dictionary_admin role")
    if (
        body.ratio_min is not None
        and body.ratio_max is not None
        and body.ratio_min > body.ratio_max
    ):
        raise GoalInvalid("ratio_min must be <= ratio_max")
    goal = await session.get(ContentGoal, body.code)
    if goal is None:
        goal = ContentGoal(code=body.code)
        session.add(goal)
    goal.color = body.color
    goal.ratio_min = body.ratio_min
    goal.ratio_max = body.ratio_max
    goal.status = "active"
    goal.updated_at = _now()
    await session.flush()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content_goal.upsert",
        entity_type="content_goal",
        entity_id=goal.code,
        detail={"color": goal.color, "ratio_min": goal.ratio_min, "ratio_max": goal.ratio_max},
    )
    return goal


async def archive_goal(session, code: str, actor) -> None:
    if ROLE_DICT_ADMIN not in actor.roles:
        raise GateNotAllowed("contentGoals edit requires dictionary_admin role")
    goal = await session.get(ContentGoal, code)
    if goal is None:
        raise GoalNotFound(code)
    goal.status = "archived"
    goal.updated_at = _now()
    await append_audit(
        session,
        tenant_id=PLATFORM_TENANT,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="content_goal.archive",
        entity_type="content_goal",
        entity_id=code,
    )


# ---------- Q27 库容配置 ----------

async def get_pool_config(session, product_space_id: str) -> dict:
    row = await session.get(PwcPoolConfig, product_space_id)
    return {
        "capacity": pwc_rules.DEFAULT_CAPACITY if row is None else row.capacity,
        "target_platforms": [] if row is None else list(row.target_platforms or []),
        "high_reuse_n": None if row is None else row.high_reuse_n,
        "configured": row is not None,
    }


async def set_pool_config(session, product_space_id: str, body, actor) -> PwcPoolConfig:
    if pwc_rules.ROLE_OPERATIONS not in actor.roles:
        raise GateNotAllowed("pool config requires operations role")
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)
    row = await session.get(PwcPoolConfig, product_space_id)
    if row is None:
        row = PwcPoolConfig(product_space_id=product_space_id)
        session.add(row)
    row.capacity = body.capacity  # None=无上限（Q27）
    row.target_platforms = body.target_platforms
    row.high_reuse_n = body.high_reuse_n
    row.updated_by = actor.id
    row.updated_at = _now()
    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pwc.pool_config",
        entity_type="pwc_pool_config",
        entity_id=product_space_id,
        detail={
            "capacity": row.capacity,
            "target_platforms": row.target_platforms,
            "high_reuse_n": row.high_reuse_n,
        },
    )
    return row


# ---------- Q21 漏斗 ----------

async def run_funnel(session, product_space_id: str, body, actor) -> list[ConditionPackage]:
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)
    pool = (
        await session.scalars(
            select(FieldPool).where(FieldPool.product_space_id == product_space_id)
        )
    ).first()
    if pool is None or pool.gate != "approved":
        raise PoolNotApproved("PWC funnel requires an approved FieldPool")

    batch_size = body.batch_size or pwc_rules.SINGLE_RUN_MAX
    if len(body.combos) > batch_size:
        raise InvalidFunnel(
            f"funnel run has {len(body.combos)} combos, exceeding single-run cap {batch_size} (Q21)"
        )

    active_goals = {
        g.code for g in await list_goals(session)
    }

    # 结构校验 + 原子装载（Q21 预筛的确定性部分；AI 预筛随 M10）。
    atom_ids = sorted({aid for c in body.combos for aid in c.atom_ids})
    atoms = {
        a.atom_id: a
        for a in (
            await session.scalars(
                select(ProductAtomInstance).where(
                    ProductAtomInstance.atom_id.in_(atom_ids)
                )
            )
        ).all()
    }
    seen_sets: set[frozenset] = set()
    loaded: list[tuple] = []
    for combo in body.combos:
        id_set = frozenset(combo.atom_ids)
        if len(id_set) < len(combo.atom_ids):
            raise InvalidFunnel("combo contains duplicate atoms")
        if id_set in seen_sets:
            raise InvalidFunnel("duplicate atom combo within the same funnel run")
        seen_sets.add(id_set)
        missing = [a for a in combo.atom_ids if a not in atoms]
        if missing:
            raise InvalidFunnel(f"atoms not found: {','.join(sorted(missing))}")
        combo_atoms = [atoms[a] for a in combo.atom_ids]
        for a in combo_atoms:
            if a.product_space_id != product_space_id:
                # Q24：PWC 严禁跨产品/跨客户复用。
                raise InvalidFunnel(f"atom {a.atom_id} belongs to another product space")
            if a.tenant_id != ps.tenant_id:
                raise InvalidFunnel(f"atom {a.atom_id} belongs to another tenant")
            if a.status != ATOM_APPROVED:
                # frozen=单条暂停（Q20）、compliance_suspended/deprecated 等不可入组合。
                raise InvalidFunnel(
                    f"atom {a.atom_id} is {a.status}, only approved atoms are usable"
                )
        dims = {a.dimension_id for a in combo_atoms if a.dimension_id}
        if len(dims) < 2:
            # 跨字段相撞：组合原子须来自 ≥2 个字段【实现补：原文未给最小组合宽度】。
            raise InvalidFunnel("combo must span at least two field dimensions")
        unknown_goals = [g for g in combo.goals if g not in active_goals]
        if unknown_goals:
            raise InvalidFunnel(
                f"unknown or inactive contentGoals: {','.join(unknown_goals)}"
            )
        loaded.append((combo, combo_atoms))

    entries = await wl_service.active_entries(
        session, industry=ps.industry_tag, now=_now()
    )

    # 待用池现状（Q22b 多样性/Q23 去重都对"待用池中各已存在组合"计算）。
    ready_pwcs = (
        await session.scalars(
            select(ConditionPackage).where(
                ConditionPackage.product_space_id == product_space_id,
                ConditionPackage.gate_status == pwc_rules.GATE_APPROVED,
                ConditionPackage.status == pwc_rules.PWC_READY,
            )
        )
    ).all()
    ready_sets: dict[str, frozenset] = {}
    for p in ready_pwcs:
        items = await session.scalars(
            select(PwcComboItem.atom_id).where(PwcComboItem.pwc_id == p.pwc_id)
        )
        ready_sets[p.pwc_id] = frozenset(items.all())

    created: list[ConditionPackage] = []
    for combo, combo_atoms in loaded:
        text_blob = " ".join(a.content for a in combo_atoms)
        hits = wl_service.match_words(text_blob, entries)
        ban_hits = [h for h in hits if h.action == "ban"]
        downgrade_hits = [h for h in hits if h.action == "downgrade"]

        id_set = frozenset(a.atom_id for a in combo_atoms)
        overlaps = {
            pid: pwc_rules.overlap_ratio(id_set, other)
            for pid, other in ready_sets.items()
        }
        max_pid = max(overlaps, key=overlaps.get, default=None)
        max_overlap = overlaps[max_pid] if max_pid else 0.0

        outcome = pwc_rules.score_combo(
            logic=combo.logic_score,
            fit=combo.fit_score,
            max_pool_overlap=max_overlap,
        )
        dup = pwc_rules.is_duplicate(max_overlap)
        is_backup = False
        if dup and max_pid is not None and outcome.scored:
            keeper = next(p for p in ready_pwcs if p.pwc_id == max_pid)
            is_backup = keeper.score is not None and outcome.score < keeper.score

        blocked = bool(ban_hits)  # Q22a：词表命中 block 直接阻断，不进评分语义
        pwc = ConditionPackage(
            tenant_id=ps.tenant_id,
            product_space_id=product_space_id,
            weight=combo.weight,
            goals=list(combo.goals),
            strategy_refs=list(combo.strategy_refs),
            structure_refs=list(combo.structure_refs),
            expression_refs=list(combo.expression_refs),
            compliance_result={
                "ban": [{"word": h.word, "level": h.level} for h in ban_hits],
                "downgrade": [
                    {"word": h.word, "level": h.level} for h in downgrade_hits
                ],
            },
            score=outcome.score,
            score_detail=outcome.detail,
            score_incomplete=outcome.needs_manual_gate,
            source=body.source,
            dup_of=max_pid if dup else None,
            is_backup=is_backup,
            gate_status=(
                pwc_rules.GATE_BLOCKED if blocked else pwc_rules.GATE_PENDING
            ),
            status=(
                pwc_rules.PWC_BLOCKED if blocked else pwc_rules.PWC_PENDING_GATE
            ),
            submitted_by=actor.id,
        )
        session.add(pwc)
        await session.flush()
        for a in combo_atoms:
            session.add(
                PwcComboItem(
                    pwc_id=pwc.pwc_id,
                    atom_id=a.atom_id,
                    dimension_id=a.dimension_id,
                    fid=a.fid,
                )
            )
        created.append(pwc)

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pwc.funnel_run",
        entity_type="product_space",
        entity_id=product_space_id,
        detail={
            "combos": len(created),
            "source": body.source,
            "blocked": sum(1 for p in created if p.gate_status == pwc_rules.GATE_BLOCKED),
            "batch_size": batch_size,
        },
    )
    return created


# ---------- 查询 / Gate ----------

async def list_pwcs(
    session, product_space_id: str, status: str | None = None
) -> Sequence[ConditionPackage]:
    stmt = select(ConditionPackage).where(
        ConditionPackage.product_space_id == product_space_id
    )
    if status is not None:
        stmt = stmt.where(ConditionPackage.status == status)
    return (
        await session.scalars(
            stmt.order_by(ConditionPackage.score.desc().nullslast(), ConditionPackage.created_at)
        )
    ).all()


async def list_combo_items(session, pwc_ids: list[str]) -> dict[str, list[PwcComboItem]]:
    if not pwc_ids:
        return {}
    rows = (
        await session.scalars(
            select(PwcComboItem).where(PwcComboItem.pwc_id.in_(pwc_ids))
        )
    ).all()
    out: dict[str, list[PwcComboItem]] = {}
    for item in rows:
        out.setdefault(item.pwc_id, []).append(item)
    return out


async def gate(session, pwc_id: str, decision: str, reason: str | None, actor) -> ConditionPackage:
    pwc = await session.get(ConditionPackage, pwc_id)
    if pwc is None:
        raise PwcNotFound(pwc_id)
    if pwc_rules.ROLE_REVIEWER not in actor.roles:
        raise GateNotAllowed("PWC Gate requires product_reviewer role")

    if decision == "reject":
        if pwc.status == pwc_rules.PWC_ARCHIVED:
            raise GateNotAllowed("PWC already archived")
        pwc.status = pwc_rules.PWC_ARCHIVED
        pwc.reject_reason = reason
        pwc.decided_by = actor.id
        pwc.decided_at = _now()
        action = "pwc.reject"
    else:
        if pwc.gate_status != pwc_rules.GATE_PENDING:
            raise GateNotAllowed(
                f"PWC gate_status is {pwc.gate_status}, only pending combos can be approved"
            )
        if pwc.status != pwc_rules.PWC_PENDING_GATE:
            raise GateNotAllowed(f"PWC is {pwc.status}, not pending Gate")
        cfg = await get_pool_config(session, pwc.product_space_id)
        if cfg["capacity"] is not None:
            ready_count = await _ready_count(session, pwc.product_space_id)
            if ready_count >= cfg["capacity"]:
                raise CapacityFull(
                    f"ready pool holds {ready_count}, capacity {cfg['capacity']} (Q27)"
                )
        pwc.gate_status = pwc_rules.GATE_APPROVED
        pwc.status = pwc_rules.PWC_READY
        pwc.decided_by = actor.id
        pwc.decided_at = _now()
        action = "pwc.approve"

    await append_audit(
        session,
        tenant_id=pwc.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action=action,
        entity_type="condition_package",
        entity_id=pwc_id,
        detail={"reason": reason, "score": pwc.score, "score_incomplete": pwc.score_incomplete},
    )
    return pwc


async def _ready_count(session, product_space_id: str) -> int:
    rows = await session.scalars(
        select(ConditionPackage.pwc_id).where(
            ConditionPackage.product_space_id == product_space_id,
            ConditionPackage.gate_status == pwc_rules.GATE_APPROVED,
            ConditionPackage.status == pwc_rules.PWC_READY,
        )
    )
    return len(rows.all())


# ---------- Q71 消费 / Q24 冷却 ----------

async def consume(session, product_space_id: str, body, actor, *, now: datetime | None = None) -> dict:
    now = now or _now()
    ps = await session.get(ProductSpace, product_space_id)
    if ps is None:
        raise ProductSpaceNotFound(product_space_id)

    await _release_expired_cooldowns(session, product_space_id, now)

    candidates = (
        await session.scalars(
            select(ConditionPackage)
            .where(
                ConditionPackage.product_space_id == product_space_id,
                ConditionPackage.gate_status == pwc_rules.GATE_APPROVED,
                ConditionPackage.status == pwc_rules.PWC_READY,
            )
            .order_by(
                ConditionPackage.score.desc().nullslast(), ConditionPackage.created_at
            )
        )
    ).all()

    used_keys = set(
        (
            await session.scalars(
                select(PwcUsageRecord.pwc_id).where(
                    PwcUsageRecord.tenant_id == ps.tenant_id,
                    PwcUsageRecord.platform == body.platform,
                    PwcUsageRecord.account == body.account,
                    PwcUsageRecord.slot == body.slot,
                )
            )
        ).all()
    )
    states = {
        s.pwc_id: s
        for s in (
            await session.scalars(
                select(PwcPlatformState).where(
                    PwcPlatformState.pwc_id.in_([p.pwc_id for p in candidates]),
                    PwcPlatformState.platform == body.platform,
                )
            )
        ).all()
    }

    picked = None
    for pwc in candidates:
        if pwc.pwc_id in used_keys:
            continue
        st = states.get(pwc.pwc_id)
        if st is not None and st.state == "cooldown":
            continue
        if not pwc_rules.goals_intersect(list(pwc.goals), body.goals):
            continue
        picked = pwc
        break
    if picked is None:
        raise PoolEmpty("no available PWC for this platform/account/slot")

    record = PwcUsageRecord(
        tenant_id=ps.tenant_id,
        pwc_id=picked.pwc_id,
        platform=body.platform,
        account=body.account,
        slot=body.slot,
        used_by=actor.id,
        used_at=now,
    )
    session.add(record)

    state = states.get(picked.pwc_id)
    if state is None:
        state = PwcPlatformState(pwc_id=picked.pwc_id, platform=body.platform)
        session.add(state)
    window_start = now - timedelta(days=pwc_rules.COOLDOWN_WINDOW_DAYS)
    recent = (
        await session.scalars(
            select(PwcUsageRecord).where(
                PwcUsageRecord.pwc_id == picked.pwc_id,
                PwcUsageRecord.platform == body.platform,
                PwcUsageRecord.used_at >= window_start,
                PwcUsageRecord.used_at <= now,
            )
        )
    ).all()
    state.last_used_at = now
    if pwc_rules.should_cooldown(len(recent)):
        state.state = "cooldown"
        state.cooldown_until = now + timedelta(days=pwc_rules.COOLDOWN_DURATION_DAYS)

    total_usage = (
        await session.scalars(
            select(PwcUsageRecord.record_id).where(
                PwcUsageRecord.pwc_id == picked.pwc_id
            )
        )
    ).all()
    picked.usage_count = len(total_usage)
    cfg = await get_pool_config(session, product_space_id)
    if cfg["high_reuse_n"] is not None and picked.usage_count >= cfg["high_reuse_n"]:
        picked.high_reuse = True
    used_platforms = set(
        (
            await session.scalars(
                select(PwcUsageRecord.platform)
                .where(PwcUsageRecord.pwc_id == picked.pwc_id)
                .distinct()
            )
        ).all()
    )
    if pwc_rules.all_platforms_used(used_platforms, cfg["target_platforms"]):
        picked.status = pwc_rules.PWC_USED

    await append_audit(
        session,
        tenant_id=ps.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pwc.consume",
        entity_type="condition_package",
        entity_id=picked.pwc_id,
        detail={
            "platform": body.platform,
            "account": body.account,
            "slot": body.slot,
            "cooldown": state.state == "cooldown",
        },
    )

    ready_count = await _ready_count(session, product_space_id)
    return {
        "pwc": picked,
        "record": record,
        "platform_state": state,
        "pool_ready_count": ready_count,
        "pool_health": pwc_rules.pool_health(ready_count),
        # Q71：跌破 critical 自动补货；WF-04 补货通道随 M10，此处只出信号。
        "restock_hint": ready_count < pwc_rules.POOL_CRITICAL,
    }


async def _release_expired_cooldowns(session, product_space_id: str, now: datetime) -> int:
    pwc_ids = (
        await session.scalars(
            select(ConditionPackage.pwc_id).where(
                ConditionPackage.product_space_id == product_space_id
            )
        )
    ).all()
    if not pwc_ids:
        return 0
    rows = (
        await session.scalars(
            select(PwcPlatformState).where(
                PwcPlatformState.pwc_id.in_(list(pwc_ids)),
                PwcPlatformState.state == "cooldown",
            )
        )
    ).all()
    released = 0
    for st in rows:
        if pwc_rules.cooldown_over(_as_utc(st.cooldown_until), now):
            st.state = "available"
            st.cooldown_until = None
            released += 1
    return released


async def sweep_cooldowns(session, now: datetime) -> int:
    """Q24：14 天冷却到期批量回待用（每平台状态）。调度器 M10 接。"""
    rows = (
        await session.scalars(
            select(PwcPlatformState).where(PwcPlatformState.state == "cooldown")
        )
    ).all()
    released = 0
    for st in rows:
        if pwc_rules.cooldown_over(_as_utc(st.cooldown_until), now):
            st.state = "available"
            st.cooldown_until = None
            released += 1
    return released


# ---------- Q24/Q61 爆款手工标注 / 归档 ----------

async def mark_hot(session, pwc_id: str, is_hot: bool, actor) -> ConditionPackage:
    pwc = await session.get(ConditionPackage, pwc_id)
    if pwc is None:
        raise PwcNotFound(pwc_id)
    if pwc_rules.ROLE_OPERATIONS not in actor.roles:
        raise GateNotAllowed("hot mark requires operations role")
    pwc.is_hot = is_hot
    pwc.hot_at = _now() if is_hot else None
    await append_audit(
        session,
        tenant_id=pwc.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pwc.hot_mark" if is_hot else "pwc.hot_unmark",
        entity_type="condition_package",
        entity_id=pwc_id,
    )
    return pwc


async def archive_pwc(session, pwc_id: str, actor) -> ConditionPackage:
    pwc = await session.get(ConditionPackage, pwc_id)
    if pwc is None:
        raise PwcNotFound(pwc_id)
    if pwc_rules.ROLE_OPERATIONS not in actor.roles:
        raise GateNotAllowed("archive requires operations role")
    if pwc.status == pwc_rules.PWC_ARCHIVED:
        raise GateNotAllowed("PWC already archived")
    old = pwc.status
    pwc.status = pwc_rules.PWC_ARCHIVED
    pwc.decided_by = actor.id
    pwc.decided_at = _now()
    await append_audit(
        session,
        tenant_id=pwc.tenant_id,
        actor_id=actor.id,
        actor_roles=actor.roles,
        action="pwc.archive",
        entity_type="condition_package",
        entity_id=pwc_id,
        detail={"from": old},
    )
    return pwc
