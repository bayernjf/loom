"""段2 ORM 模型：C1 配置/识别记录、ops 待办、G1 类目树与模板、C7 运行记录、G2 候选。

依据 docs/04 §2.3-2.6、Q1-Q7/Q68、docs/10 §2.1。
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


class C1SignalWeight(Base):
    """Q2 信号权重配置表；启用行权重之和必须 == 1（service 层强校验）。"""

    __tablename__ = "c1_signal_weights"

    signal: Mapped[str] = mapped_column(String(32), primary_key=True)
    signal_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    # 打分方式说明（新信号上线=加行+一次性打分开发，Q2）。
    scoring_method: Mapped[str | None] = mapped_column(String(128), nullable=True)


class C1IndustryThreshold(Base):
    """Q7 行业阈值表：不可删默认档（is_default，general 0.85）+ 改动写审计。"""

    __tablename__ = "c1_industry_thresholds"

    industry: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 识别关键词或类目映射（C1 从类目路径/资料映射行业，Q7）。
    keywords: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class C1Record(Base):
    """c1Records：每次 C1 识别一条；conf 为唯一判定指标（Q1，hit_rate 废弃）。"""

    __tablename__ = "c1_records"

    record_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(
        ForeignKey("product_intake_applications.intake_id"),
        nullable=False,
        index=True,
    )
    signals: Mapped[dict] = mapped_column(JSONType, nullable=False)
    conf: Mapped[float] = mapped_column(Float, nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    branch: Mapped[str] = mapped_column(String(32), nullable=False)
    # AI Top 类目候选 [{category_id, conf}]；Top1-Top2 差<0.1 视为矛盾（Q3）。
    top_candidates: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    top_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ops_assist 分支运营选定后的类目（Q3）。
    selected_category_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class OpsTodo(Base):
    """运营待办（Q3/Q4 最小实现）。

    M10 会落通用 SLA 引擎（Q49/Q70）；本表仅服务 M2 的类目确认待办，
    到期未处理经 sweep 置 escalated（主管/看板高亮）。
    """

    __tablename__ = "ops_todos"

    todo_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    todo_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    assignee_role: Mapped[str] = mapped_column(String(32), nullable=False, default="operations")
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class G1Category(Base):
    """G1 类目树：跨产品共享（Q24）；状态机 active/draft/review/deprecated/
    archived/merged，merged 带 merged_into 永久重定向。"""

    __tablename__ = "g1_categories"

    category_id: Mapped[str] = _uuid_pk()
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("g1_categories.category_id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    merged_into: Mapped[str | None] = mapped_column(
        ForeignKey("g1_categories.category_id"), nullable=True
    )
    product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()


class G1CategoryTemplate(Base):
    """叶子类目模板；field_list 只允许持合法 G2 fid（Q68，禁止 fid:'-'）。"""

    __tablename__ = "g1_category_templates"

    category_id: Mapped[str] = mapped_column(
        ForeignKey("g1_categories.category_id"), primary_key=True
    )
    field_list: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft"
    )  # draft/approved
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class C7Run(Base):
    """c7Runs：四层兜底每次执行留痕（line 708，Q6）。"""

    __tablename__ = "c7_runs"

    run_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    category_id: Mapped[str] = mapped_column(String(36), nullable=False)
    layer: Mapped[int] = mapped_column(Integer, nullable=False)
    field_list: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class G2FieldCandidate(Base):
    """g2FieldCandidates（04 §2.6）：C7 Layer4 / 后续 WF-02 新字段入口。

    转正走人工 Gate（Q13 字典管理员权限），不在段2落地。
    来源租户可见性挂账（04 §2.6 待补，多租户设计时定），tenant_id 先可空。
    """

    __tablename__ = "g2_field_candidates"
    __table_args__ = (UniqueConstraint("source_layer", "field_name", name="uq_candidate_source_name"),)

    candidate_id: Mapped[str] = _uuid_pk()
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    # c7_layer4 / wf02_dim_source 等（维度依据红线：须标来源）。
    source_layer: Mapped[str] = mapped_column(String(32), nullable=False)
    source_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    dup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    related_fid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 枚举原文未给完整集，04 §2.6 建议三态；候选状态完整枚举仍挂账。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_gate", index=True
    )
    created_at: Mapped[datetime] = _created_at()
