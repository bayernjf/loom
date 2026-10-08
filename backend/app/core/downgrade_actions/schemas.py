"""Q38 降级动作字典的请求/响应模型。

调用方身份**不在正文里**（`actor` 字段属旧自报口径）——两口写端点走 Q203/Q242 的
`require_internal_actor`，身份由服务端令牌派生。
"""

from pydantic import BaseModel


class DowngradeActionUpsert(BaseModel):
    code: str
    name: str | None = None
    why: str | None = None
