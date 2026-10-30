"""需要「已验真客户访问令牌」的端点的测试侧统一入口（P0，2026-10-30）。

客户内容决策端点（approve/reject/revise/body）自 P0 起只认已验真的 ``loom_client_``
令牌：门控关闭时它们也自行验真，所以「正文里自报 actor」不再是身份。测试要打
这些口，就得先按上线口径拿到一枚令牌——门控关下自报 operations 经
``POST /api/admin/client-keys`` 引导签发。这里把引导路径收在一处，免得每个文件各抄。

客户令牌绑定租户，签发时的 ``tenant_id`` 必须与请求 query 的 ``tenant_id`` 一致；
认证身份的 ``actor.id`` 取 ``client_name``，角色为 ``whitelist_owner``。
"""

from typing import Any

from httpx import AsyncClient

BOOTSTRAP_OPS: dict[str, Any] = {"id": "ops-bootstrap", "roles": ["operations"]}


async def issue_client_token(
    client: AsyncClient,
    tenant_id: str,
    *,
    client_name: str = "cust-1",
) -> str:
    """引导签发一枚绑定租户的客户令牌并返回明文（明文仅签发响应出现一次）。"""
    resp = await client.post(
        "/api/admin/client-keys",
        json={
            "tenant_id": tenant_id,
            "client_name": client_name,
            "actor": BOOTSTRAP_OPS,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


def client_bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}
