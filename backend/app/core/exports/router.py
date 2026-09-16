"""M12 中台导出端点（Q100）。"""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exports import service

router = APIRouter(prefix="/api/exports", tags=["middleground-export"])


@router.get("/fcw.csv")
async def export_fcw_csv(
    tenant_id: str = Query(min_length=1),
    product_space_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    # Q100：中台手动拉取白名单 final_id 单列。读路径不触发 Q95 准入门
    # （未知租户=仅表头空文件 200）；只导 published（draft 排除，Q32
    # revoked 落地后同过滤自然生效）。
    final_ids = await service.exported_final_ids(
        session, tenant_id=tenant_id, product_space_id=product_space_id
    )
    body = service.render_csv(final_ids)
    filename = f"fcw-{tenant_id}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
