"""M12 中台导出（Q100）：FCW final_id 单列 CSV。

契约（docs/05 D4，02 C1.44 拍板）：中台手动用，M12 验收口径“CSV 只消费
final_id”——仅导一列 final_id（含表头），不拼装 6 层原料包。读路径同
Q98/Q99：不触发 Q95 准入门，未知租户返回仅表头空文件；只导 published
（draft 不导出；Q32 revoked 急停操作 V1 尚未落地，其态一旦实现亦自然
被 published 过滤排除——前向兼容）。JSON 导出不在本切片（09 D5 虽提
CSV/JSON，D4/M12 仅要求 CSV，挂账后续）。
"""

import csv
import io

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.final.final_whitelist.models import (
    PUBLISH_PUBLISHED,
    FinalContentWhitelist,
)

CSV_HEADER = ("final_id",)


async def exported_final_ids(
    session: AsyncSession,
    *,
    tenant_id: str,
    product_space_id: str | None = None,
) -> list[str]:
    stmt = (
        select(FinalContentWhitelist.final_id)
        .where(
            FinalContentWhitelist.tenant_id == tenant_id,
            FinalContentWhitelist.publish_status == PUBLISH_PUBLISHED,
        )
        .order_by(FinalContentWhitelist.created_at.desc())
    )
    if product_space_id:
        stmt = stmt.where(
            FinalContentWhitelist.product_space_id == product_space_id
        )
    rows = await session.scalars(stmt)
    return list(rows.all())


def render_csv(final_ids: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows((final_id,) for final_id in final_ids)
    return buffer.getvalue()
