"""段9 三包（CSP/CSTP/CEP）配置实例 ORM 模型（V1 静态切片，08 M11）。

Q52：区分"底座选项"（全租户共享字典）与"配置实例"（为某产品配出的那份包）——
实例落库即带 product_space_id + tenant_id，段11 Guard④⑤ 校验实例归属。
Q45：按（产品×平台×目的）三元组配一份并缓存复用；满 20 次或 PCP 更新触发
重配走 Gate——重配与 WF-07 AI 选料随 V2（08 P2），V1 为运营手工配置实例。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType

KIND_CSP = "csp"
KIND_CSTP = "cstp"
KIND_CEP = "cep"
PACKAGE_KINDS = (KIND_CSP, KIND_CSTP, KIND_CEP)

# 04 §2.17（line 863）：各包字段名完整；payload 键集按 kind 校验【实现补】。
KIND_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    KIND_CSP: ("goal", "stage", "angle", "intensity", "cta", "emotion"),
    KIND_CSTP: ("struct",),
    KIND_CEP: ("tone", "perspective", "explicit", "soften"),
}


class Package(Base):
    """CSP/CSTP/CEP 配置实例：按（产品×平台×目的×包型）唯一 active 一份。"""

    __tablename__ = "packages"

    package_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product_space_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    gate: Mapped[str] = mapped_column(String(16), nullable=False, default="approved")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
