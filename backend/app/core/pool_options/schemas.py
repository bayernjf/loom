"""Q43 池选项字典的请求模型（身份不在正文里，走 require_internal_actor 派生）。"""

from pydantic import BaseModel


class PoolOptionUpsert(BaseModel):
    pool: str
    options: list[str] | None = None
