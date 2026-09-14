"""段7/8 静态底表 ORM 模型（08 M11：FCW 6 路输入的平台/策略侧最小切片）。

- publish_slots：发布位档案（Q35 后台 CRUD，客观字段附来源链接，四维分=人工评估）；
- goal_fit_weights：Q34 目的→四维权重矩阵（Σ=1）；
- platform_rules：平台规则（4 层选择器 + country modifier，effect 仅 blocked/partial）；
- slot_type_defaults：slotType 默认值（13 类约 40 列原文未全给出，先落发布限量）；
- pcp_templates / pcp_weight_tables：段8 17 池权重（Q39 模板派生，Q52 配置实例
  带 product_space_id/tenant_id，PT-PCP-V1.5 平台间不共享）。

动态信号（Q37）/每周重算（Q41/Q42 AI 通道）/fit_score 学习均随 V2，不在本切片。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
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


class PublishSlot(Base):
    """发布位档案（04 §2.12）：14 平台 100+ 发布位、slotType 13 类——

    平台/发布位/slotType 全量目录在基准 HTML line 1098-1221/1428，文件缺失，
    【原文未给出，待补】故 V1 不做种子，由后台 CRUD 逐条录入。
    """

    __tablename__ = "publish_slots"

    slot_id: Mapped[str] = _uuid_pk()
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slot_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    chars_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dur_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dur_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 四维静态分（0-100）：主观字段，明示"人工评估"（Q35）。
    traffic: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    safe: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    conv: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    load: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    score_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual_eval"
    )
    risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gate: Mapped[str] = mapped_column(String(16), nullable=False, default="approved")
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class GoalFitWeight(Base):
    """Q34：内容目的 → 四维权重矩阵（挂 Q25 contentGoals，Σ=1 强校验）。"""

    __tablename__ = "goal_fit_weights"

    goal: Mapped[str] = mapped_column(String(32), primary_key=True)
    weights: Mapped[dict] = mapped_column(JSONType, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class PlatformRule(Base):
    """平台规则（04 §2.13）：effect 仅 blocked/partial（native 默认不存）。

    country 为横切 modifier（空=适用全部市场）；<300 条覆盖 ~10 万理论格子的
    结构性约束靠选择器层级而非行数达成。R-X01~X05 跨层矛盾检测原文在基准 HTML
    line 1383，文件缺失【待补】，V1 不落。
    """

    __tablename__ = "platform_rules"

    rule_id: Mapped[str] = _uuid_pk()
    selector_level: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    slot_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    slot_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    effect: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class SlotTypeDefault(Base):
    """slotType 默认值（04 §2.14）：优先级最低、可被逐位覆盖。

    原文只给出单账号日发布限量（主 2-3/互动 3-5/短视频 1-3）；约 40 列全量
    定义在基准 HTML line 1428【原文未给出，待补】，defaults JSON 先行占位。
    """

    __tablename__ = "slot_type_defaults"

    slot_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    daily_limit_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_limit_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    defaults: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class PcpTemplate(Base):
    """Q39：4 套平台类型模板（短视频/社区讨论/图文种草/电商），17 池权重初值。

    初值为实现阶段起草的起点（Q39"模板初值起草放实现阶段"），回流后校准——
    【实现补：初值草稿】，数值非原文规格。
    """

    __tablename__ = "pcp_templates"

    template_id: Mapped[str] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    weights: Mapped[dict] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = _created_at()


class PcpWeightTable(Base):
    """段8 PCP 17 池权重配置实例（Q52：带 product_space_id/tenant_id）。

    【实现补：V1 静态切片】按（产品×平台）实例化，同产品同平台仅 1 条 active；
    平台间不共享（PT-PCP-V1.5）。Q41 每周重算/动态信号触发随 V2。
    """

    __tablename__ = "pcp_weight_tables"
    __table_args__ = (
        UniqueConstraint("product_space_id", "platform", name="uq_pcp_ps_platform"),
    )

    pcp_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    template_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weights: Mapped[dict] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
