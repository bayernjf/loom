"""需要「已验真 staff 令牌」的端点的测试侧统一入口（Q203 #34）。

E1.1 两个发证写口自 Q203 起只认已验真令牌：门控关闭时它们**仍自行验真**，
所以「正文里自报 operations」不再是身份。测试要打这两个口，就得先按 Q178 的
上线口径拿到一枚令牌——门控关下自报 platform_admin 经 ``POST /api/admin/staff-keys``
引导签发。这里把这条引导路径收在一处，免得每个文件各抄一遍。

注意：使用本模块的测试，其 ``session_factory`` 夹具必须同时
``app.dependency_overrides[get_auth_session] = get_test_session``，
否则验真会去连应用真实的 SessionLocal，与测试内存库不是同一个库。
"""

from typing import Any

from httpx import AsyncClient

BOOTSTRAP_ADMIN: dict[str, Any] = {"id": "pa-bootstrap", "roles": ["platform_admin"]}


async def issue_staff_token(
    client: AsyncClient,
    roles: list[str],
    *,
    staff_id: str = "s-ops",
    staff_name: str = "运营值班",
) -> str:
    """引导签发一枚 staff 令牌并返回明文（明文只在签发响应里出现一次）。"""
    resp = await client.post(
        "/api/admin/staff-keys",
        json={
            "staff_id": staff_id,
            "staff_name": staff_name,
            "roles": roles,
            "actor": BOOTSTRAP_ADMIN,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


def bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}
