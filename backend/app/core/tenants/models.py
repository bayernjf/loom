"""租户注册表（Q95，docs/09 D3.11）。

V1 共享实例多租户的权威实体：plan 四档（trial/basic/pro/enterprise）、
status 三态（trial/active/paused）。价格仅展示用（不落库、不做计费拦截，
D3.11-6 计费随 V2）；额度只存试用档月度 token 额度（原文仅给试用档数值，
其余档【原文未给出，待补】），本切片不做任何额度消耗拦截。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType

PLANS = ("trial", "basic", "pro", "enterprise")
STATUSES = ("trial", "active", "paused")

# docs/09 D3.11 line 1466：试用版月度 token 额度 50 万；其余档位原文未给。
TRIAL_MONTHLY_TOKEN_QUOTA = 500_000


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plan: Mapped[str] = mapped_column(String(16), default="trial", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="trial", nullable=False, index=True
    )
    monthly_token_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 回填标记等机读元数据（0023 回填行 {"backfilled": true}）。
    detail: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    plan_changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
