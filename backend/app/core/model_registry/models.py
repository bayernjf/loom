"""统一模型注册表、场景路由、outbound Key、Prompt 版本化模板（Q67/Q82）。

物理表字段补登（04 §2.24 原文只给一行字段名，字段级定义属开发补规格范围）：
- ai_models：模型/供应商/per-1M 入出价/日预算/状态/fallback（Q67）；
  currency_code 原文未给出，可空并标【原文未给出，待补】，不猜币种。
- ai_model_keys：供应商密钥密文（DB 加密 + env 主密钥，Q82-3），明文不回显，
  轮换=旧钥置 revoked + 插新行。
- ai_scene_routes：场景（= skill_id）→ 默认模型，运营可改不动代码（Q67）。
- skill_prompts / skill_prompt_versions：Prompt DB 版本化（07 §7.3，Q82-4），
  v0.1 起步，历史 append-only，Prompt 修改=RBAC 红线 + writeAudit。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JSONType


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid1()))


class AIModel(Base):
    __tablename__ = "ai_models"

    model_id: Mapped[str] = _uuid_pk()
    # 机读码，驱动/路由按此识别（如 synthetic-deterministic）。
    model_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    input_price_per_1m: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    output_price_per_1m: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    # 币种原文未给【待补】；None 不参与真实计费展示。
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # None=不限预算；超限硬停（Q82 实现补登）。
    daily_budget: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    # active / disabled；disabled 时路由指 fallback_model_id（不做失败自动转移）。
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Q86：chat=生成式场景（invoke），embedding=向量化场景（embed）。
    capability: Mapped[str] = mapped_column(String(16), nullable=False, default="chat")
    fallback_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_models.model_id"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AIModelKey(Base):
    """outbound 供应商密钥；一模型一 active 行，轮换保留 revoked 历史。"""

    __tablename__ = "ai_model_keys"

    key_id: Mapped[str] = _uuid_pk()
    model_id: Mapped[str] = mapped_column(
        ForeignKey("ai_models.model_id"), nullable=False, index=True
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # 仅展示末 4 位，明文永不回显（Q82-3）。
    fingerprint: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AISceneRoute(Base):
    __tablename__ = "ai_scene_routes"

    # 场景键 = skill_id（Q82 实现补登：skill 即场景，不再造一层枚举）。
    scene: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ai_models.model_id"), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillPrompt(Base):
    """每个 Skill 当前生效的 Prompt 版本指针；版本历史在 SkillPromptVersion。"""

    __tablename__ = "skill_prompts"

    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_version: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillPromptVersion(Base):
    __tablename__ = "skill_prompt_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_prompt_version"),
    )

    version_id: Mapped[str] = _uuid_pk()
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    variables: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
