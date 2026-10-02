"""段11 FCW（final content whitelist）物理模型（08 M8）。

唯一出口红线（line 11036）：final_id 仅由 E1.1 publishFCW（本包组装服务）
生成；任何其他模块写入 final_id 均为协议违反。
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
from app.final.final_whitelist import exit_guard


def _uuid_pk() -> str:
    return str(uuid.uuid1())  # 时间有序，同秒内仍唯一

PUBLISH_DRAFT = "draft"
PUBLISH_PUBLISHED = "published"

TASK_STATUS_COMPLETED = "completed"

# FCW 版本快照状态（Q251，design-fcw-freeze-management 3.1 甲）。
FCW_SNAP_FROZEN = "frozen"
FCW_SNAP_SUPERSEDED = "superseded"
FCW_SNAP_REVOKED = "revoked"
FCW_SNAP_VERSION_V1 = "v1"

FCW_FREEZE_EVENT_FREEZE = "freeze"
FCW_FREEZE_EVENT_REVOKE = "revoke"


class FinalContentWhitelist(Base):
    """FCW 组装成品（01 line 870 字段集）。

    6 路输入以 id 引用留痕（pws/pcp/csp/cstp/cep/ccr）；guards JSON 保存
    发证时 7 项机械核验明细（Q55 审计：六路材料 + Guard 结果）。
    """

    __tablename__ = "final_content_whitelists"
    __table_args__ = (
        # 【实现补】同冻结版×同骨架×同平台×同发布位不重复发证（Q24/Q71 去重精神
        # 落到组装口；country 维度的同键去重由服务层处理，NULL 不入 DB 约束）。
        UniqueConstraint(
            "pws_id", "pwc_id", "platform", "slot_id", name="uq_fcw_same_issue"
        ),
    )

    final_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pws_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pwc_id: Mapped[str] = mapped_column(String(36), nullable=False)
    pcp_id: Mapped[str] = mapped_column(String(36), nullable=False)
    csp_package_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cstp_package_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cep_package_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ccr_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    law_review_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slot_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    score_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guards: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    guards_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    publish_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PUBLISH_PUBLISHED, index=True
    )
    issued_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FcwSnapshot(Base):
    """FCW 版本快照（Q251，design-fcw-freeze-management §3.1 甲，参照 pws_snapshots）。

    final_id 级：每个组装成品一个不可变快照行，版本恒 v1、状态 frozen
    （is_active=true 表达"当前版本"）；作废即 revoked（is_active=false），
    下游段12 内容生成只消费 active 且 frozen 的快照（Q32 断消费哲学）。
    snapshot JSON 以 id 引用 6 路输入 + 发证时评分与 guards 明细（不可变物化）。
    """

    __tablename__ = "fcw_snapshots"
    __table_args__ = (
        UniqueConstraint("final_id", "version", name="uq_fcw_final_version"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    final_id: Mapped[str] = mapped_column(
        ForeignKey("final_content_whitelists.final_id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)

    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONType, nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class FcwFreezeLog(Base):
    """FCW 冻结事件流水（freeze/revoke＋操作人＋原因；只增不 mutate）。

    与 pws_freeze_logs 同构：每次红线动作（发证即冻结、作废）记触发原因、
    操作人与 Q 依据，状态列不承载历史。
    """

    __tablename__ = "fcw_freeze_logs"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    final_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    # freeze / revoke
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# 模块导入即把「唯一出口」装成运行期守卫（Q203 #34 后半）：只要有人拿到这个模型，
# 在 E1.1 之外 flush 一条成品就会判红——不依赖他是否记得 import 守卫模块。
exit_guard.install(FinalContentWhitelist)


class FcwAssemblyTask(Base):
    """Q55 任务驱动批量发证：产品×平台×目的×数量 → 逐条机械配料过 Guard。

    V1 同步执行（请求内逐条组装），异步队列随 M10 调度；results JSON 留痕
    每条 final_id 或未发证原因。
    """

    __tablename__ = "fcw_assembly_tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_pk)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    pws_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    goal: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_ids: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    results: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
