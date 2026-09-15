"""统一审核工作台 Pydantic 契约（Q93，05 Q93 补登）。"""

from pydantic import BaseModel, Field

from app.core.actor import Actor


class BatchApproveRequest(BaseModel):
    # 整批单事务 all-or-nothing；只允许 confirmed（原样通过），
    # modified 必须逐条走既有 /api/skill-candidates/{id}/decision。
    candidate_ids: list[str] = Field(min_length=1)
    reason: str | None = None
    actor: Actor
