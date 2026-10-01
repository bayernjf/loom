"""需要「已验真 staff 令牌」的端点的测试侧统一入口（Q203 #34）。

E1.1 两个发证写口自 Q203 起只认已验真令牌：门控关闭时它们**仍自行验真**，
所以「正文里自报 operations」不再是身份。测试要打这两个口，就得先按 Q178 的
上线口径拿到一枚令牌——门控关下自报 platform_admin 经 ``POST /api/admin/staff-keys``
引导签发。这里把这条引导路径收在一处，免得每个文件各抄一遍。

注意：使用本模块的测试，其 ``session_factory`` 夹具必须同时
``app.dependency_overrides[get_auth_session] = get_test_session``，
否则验真会去连应用真实的 SessionLocal，与测试内存库不是同一个库。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import AsyncClient

BOOTSTRAP_ADMIN: dict[str, Any] = {"id": "pa-bootstrap", "roles": ["platform_admin"]}

# Q242：段4/7/8/10 的写口各自要求 operations / product_reviewer / internal_compliance
# 之一。集成测试多半要跑完整条链（建池→审原子→发证），逐口换令牌只是噪音，
# 故给这些文件的默认 client 一枚同时覆盖三口的令牌。
DEFAULT_WRITE_ROLES = ["operations", "product_reviewer", "internal_compliance"]


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


async def issue_write_token(client: AsyncClient, *, staff_id: str = "s-writer") -> str:
    """一枚同时具备三个内部写口角色的令牌（Q242 默认身份）。"""
    return await issue_staff_token(
        client, DEFAULT_WRITE_ROLES, staff_id=staff_id, staff_name="写口值班"
    )


@asynccontextmanager
async def acting_as(
    client: AsyncClient, roles: list[str], *, staff_id: str = "s-alt"
) -> AsyncIterator[None]:
    """临时换一枚角色不同的令牌打单个口，退出时还原原来的 Authorization 头。

    Q242 起「越权」不再是正文自报一个没角色的 actor（那已不是身份），而是换一枚
    真的缺该角色的令牌，故负向用例要用它包住那一次调用。
    """
    saved = client.headers.get("Authorization")
    client.headers.update(bearer(await issue_staff_token(client, roles, staff_id=staff_id)))
    try:
        yield
    finally:
        if saved is None:
            client.headers.pop("Authorization", None)
        else:
            client.headers.update({"Authorization": saved})
