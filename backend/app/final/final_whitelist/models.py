"""段11 FCW（final content whitelist）物理模型（08 M8）。

唯一出口红线（line 11036）：final_id 仅由 E1.1 publishFCW（本包组装服务）
生成；任何其他模块写入 final_id 均为协议违反。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> str:
    return str(uuid.uuid1())  # 时间有序，同秒内仍唯一

PUBLISH_DRAFT = "draft"
PUBLISH_PUBLISHED = "published"

TASK_STATUS_COMPLETED = "completed"


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
