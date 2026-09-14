"""段5 ORM 模型：contentGoals 字典（Q25）、PWC 库容配置（Q27）、
条件包与跨字段组合明细（line 1780）、取用记录与每平台冷却状态（Q24/Q71）。

依据 docs/04 §2.10、13 §1.7、Q21-Q27、Q61/Q71。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentGoal(Base):
    """Q25 contentGoals 目的字典：录入页与 PWC 打标读同一张平台级共享表。

    名称用 line 1090 五类标准枚举码；颜色/配比上下限原文未给出具体值，
    种子留 NULL 待运营维护【原文未给出，待补】。
    """

    __tablename__ = "content_goals"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ratio_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    ratio_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PwcPoolConfig(Base):
    """Q27 产品空间级库容配置；一行一 PS。

    capacity=NULL 表示运营显式配"无上限"；未建行时取默认 100。
    target_platforms 为 Q24"全平台用尽转已用"的目标平台清单
    （来源原文未给【待补】，本列为实现补）。
    """

    __tablename__ = "pwc_pool_configs"

    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), primary_key=True
    )
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_platforms: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    # Q24 高复用打标次数 N（原文未给默认值【待补】；NULL=不自动打标）。
    high_reuse_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConditionPackage(Base):
    """conditionPackages（docs/04 §2.10，line 1780，字段完整）。"""

    __tablename__ = "condition_packages"

    pwc_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        ForeignKey("product_spaces.product_space_id"), nullable=False, index=True
    )

    # line 1780：weight；原文未定义取值语义，先透传存储【待补】。
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    goals: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    # 段9 三包引用在段10 才落地，先按 line 1780 透传 JSON。
    strategy_refs: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    structure_refs: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    expression_refs: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    # compliance{ban,downgrade,gate}：检测留痕（命中词/等级/处置）。
    compliance_result: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # score_detail{logic,fit,reasonableness,diversity,category_multiplier,w_logic,w_fit}
    score_detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    # Q22b：AI 分项缺失/超时不出分，待人工 Gate。
    score_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source: Mapped[str] = mapped_column(String(8), nullable=False)  # ai/manual/hybrid

    # Q23：疑重降权入备选（保留分高者，人工 Gate 可改判）。
    dup_of: Mapped[str | None] = mapped_column(
        ForeignKey("condition_packages.pwc_id"), nullable=True
    )
    is_backup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    gate_status: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Q24 高复用打标（次数线由库容配置 high_reuse_n 控制）。
    high_reuse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Q24/Q61：爆款第一期手工标注；自动判定（中位数 5 倍）留段13。
    is_hot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PwcComboItem(Base):
    """combo[{fp,atom}] 子表：跨字段原子组合明细（line 1780）。"""

    __tablename__ = "pwc_combo_items"
    __table_args__ = (
        UniqueConstraint("pwc_id", "atom_id", name="uq_pwc_combo_atom"),
    )

    item_id: Mapped[str] = _uuid_pk()
    pwc_id: Mapped[str] = mapped_column(
        ForeignKey("condition_packages.pwc_id"), nullable=False, index=True
    )
    atom_id: Mapped[str] = mapped_column(
        ForeignKey("product_atom_instances.atom_id"), nullable=False
    )
    # 取自原子挂载维度，便于"跨字段"校验与展示。
    dimension_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fid: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PwcUsageRecord(Base):
    """Q24/Q71 取用记录：同平台+账号+发布位仅 1 次（唯一约束即去重）。"""

    __tablename__ = "pwc_usage_records"
    __table_args__ = (
        UniqueConstraint(
            "pwc_id",
            "platform",
            "account",
            "slot",
            name="uq_pwc_usage_platform_account_slot",
        ),
    )

    record_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pwc_id: Mapped[str] = mapped_column(
        ForeignKey("condition_packages.pwc_id"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account: Mapped[str] = mapped_column(String(128), nullable=False)
    slot: Mapped[str] = mapped_column(String(64), nullable=False)
    used_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class PwcPlatformState(Base):
    """每平台消费状态：Q24 冷却是同平台口径，跨平台仍可复用。"""

    __tablename__ = "pwc_platform_states"
    __table_args__ = (
        UniqueConstraint("pwc_id", "platform", name="uq_pwc_platform_state"),
    )

    state_id: Mapped[str] = _uuid_pk()
    pwc_id: Mapped[str] = mapped_column(
        ForeignKey("condition_packages.pwc_id"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    # available / cooldown
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
