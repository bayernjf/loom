"""段11 FCW 组装 REST 端点（08 M8）。

E1.1 publishFCW 是全系统 final_id 唯一出口（line 11036）：
本路由之外任何模块写 final_content_whitelists 均为协议违反。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.config import get_settings
from app.core.db import get_session
from app.core.queue import StreamBackendError
from app.core.rbac import (
    OPERATIONS,
    PLATFORM_ADMIN,
    PermissionDenied,
    require_any_role,
)
from app.final.final_whitelist import material, service
from app.final.final_whitelist.schemas import AssemblyManual, AssemblyTaskCreate

router = APIRouter(tags=["final-whitelist"])


def _query_actor(*roles: str):
    """Q177 管理面只读口 query actor 闸（同 Q109/Q118/Q125/Q130：缺 actor_id 422、越权 403）。"""

    def dependency(
        actor_id: str = Query(...),
        roles_param: list[str] = Query(default_factory=list, alias="roles"),
    ) -> Actor:
        actor = Actor(id=actor_id, roles=roles_param)
        try:
            require_any_role(actor, *roles)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return actor

    return dependency


# 台内白名单卡片运营视图：组装发证本就要求 operations，运营台读 operations|platform_admin。
require_fcw_admin_view = _query_actor(OPERATIONS, PLATFORM_ADMIN)


def _guard_conflict(exc: service.GuardsFailed) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": "FCW guards failed; final_id not generated",
            "guards": exc.guard_results,
        },
    )


@router.post("/api/fcw/assemble")
async def assemble_manual(
    body: AssemblyManual, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        fcw = await service.assemble_one(
            session,
            product_space_id=body.product_space_id,
            platform=body.platform,
            goal=body.goal,
            slot_id=body.slot_id,
            actor=body.actor,
            country=body.country,
            pws_id=body.pws_id,
        )
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except (service.PwsNotFound, service.SlotNotFound) as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.GoalInvalid as exc:
        raise HTTPException(404, f"unknown or inactive goal: {exc}") from exc
    except service.InvalidRequest as exc:
        raise HTTPException(422, str(exc)) from exc
    except service.MaterialMissing as exc:
        raise HTTPException(409, f"materials missing: {exc}") from exc
    except service.GuardsFailed as exc:
        await session.commit()  # 保留 fcw.assembly_blocked 审计
        raise _guard_conflict(exc) from exc
    except service.DuplicateIssuance as exc:
        raise HTTPException(409, f"FCW already issued: {exc}") from exc
    await session.commit()
    return service.fcw_view(fcw)


@router.post("/api/fcw/assembly-tasks", status_code=201)
async def create_assembly_task(
    body: AssemblyTaskCreate, session: AsyncSession = Depends(get_session)
) -> dict:
    """Q55 任务驱动批量发证；Q165 门控开启时改异步入队。

    门控关（V1 默认）：请求内同步跑完，status=running→completed，七 Guard 原子性
    不变。门控开：建 queued 任务并 XADD 入流，由 FcwWorker 异步组装，前端经已有
    GET 状态口轮询。入流失败 fail-closed：删除 queued 行并回 503，不留半完成任务。
    """
    enabled = get_settings().fcw_worker_enabled
    try:
        task = await service.create_task_record(
            session,
            body,
            status=service.TASK_STATUS_QUEUED
            if enabled
            else service.TASK_STATUS_RUNNING,
        )
    except service.RoleNotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    except service.PwsNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.SlotNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.GoalInvalid as exc:
        raise HTTPException(404, f"unknown or inactive goal: {exc}") from exc
    except service.InvalidRequest as exc:
        raise HTTPException(422, str(exc)) from exc

    if not enabled:
        # V1 同步：同一 session 内逐条组装到 completed。
        task = await service.process_task(session, task, body.actor)
        await session.commit()
        return service.task_view(task)

    # Q165 异步：先提交 queued（worker 读到时任务必须已可见），再入流。
    await session.commit()
    try:
        await service.enqueue_fcw_task(task.task_id)
    except StreamBackendError:
        # 入流失败 fail-closed：删除 queued 行，绝不留无人消费的僵尸任务。
        await session.delete(task)
        await session.commit()
        raise HTTPException(
            status_code=503, detail="fcw assembly queue unavailable"
        ) from None
    return service.task_view(task)


@router.get("/api/fcw/assembly-tasks/{task_id}")
async def get_assembly_task(
    task_id: str, session: AsyncSession = Depends(get_session)
) -> dict:
    task = await service.get_task(session, task_id)
    if task is None:
        raise HTTPException(404, f"task not found: {task_id}")
    return service.task_view(task)


@router.get("/api/product-spaces/{product_space_id}/fcw")
async def list_fcw(
    product_space_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await service.list_fcw(session, product_space_id)
    return [service.fcw_view(r) for r in rows]


@router.get("/api/fcw")
async def list_tenant_fcw(
    tenant_id: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Q180 D3.5 客户卡片视图：按租户列出已发证 FCW（客户只读口）。

    客户口径同 GET /api/content（无鉴权闸、tenant_id query 必填、强制租户过滤）：
    只回本租户白名单元信息；六层原料包经 GET /api/fcw/{final_id}/material.json
    按需反解析；不触发 Guard、不写审计。
    """

    rows, _ = await service.list_fcw_admin(
        session, tenant_id=tenant_id, limit=100000, offset=0
    )
    return [service.fcw_view(r) for r in rows]


@router.get("/api/fcw/{final_id}")
async def get_fcw(final_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    fcw = await service.get_fcw(session, final_id)
    if fcw is None:
        raise HTTPException(404, f"FCW not found: {final_id}")
    return service.fcw_view(fcw)


@router.get("/api/fcw/{final_id}/material.json")
async def export_fcw_material(
    final_id: str, session: AsyncSession = Depends(get_session)
) -> JSONResponse:
    """Q155 台内卡片「导出 JSON」：该白名单完整 6 层提示词原料包（docs/09:87）。

    与中台 /api/exports/fcw.json（final_id-only）是两个面：本口按单条 final_id
    反解析产品 PWS/平台 PCP/策略 CSP/结构 CSTP/表达 CEP/合规 CCR 六层完整快照，
    供台内卡片详情/复制；只读、不触发 Guard、不写审计，未知 final_id 404。
    """

    fcw = await service.get_fcw(session, final_id)
    if fcw is None:
        raise HTTPException(404, f"FCW not found: {final_id}")
    pack = await material.build_material_pack(session, fcw)
    return JSONResponse(
        content=jsonable_encoder(pack),
        headers={
            "Content-Disposition": f'attachment; filename="fcw-material-{final_id}.json"'
        },
    )


@router.get("/api/admin/fcw")
async def admin_list_fcw(
    tenant_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_fcw_admin_view),
) -> dict:
    """Q177 D3.5 白名单组装引擎运营只读首片：跨租户分页浏览已发证 FCW。

    与按产品空间的 GET /api/product-spaces/{id}/fcw（中台/客户口径）不同，本口
    供管理端运营台跨租户查看；tenant_id 可选过滤，只回元信息、不含六层大包。
    """

    rows, total = await service.list_fcw_admin(
        session, tenant_id=tenant_id, limit=limit, offset=offset
    )
    return {
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "items": [service.fcw_view(r) for r in rows],
    }


@router.get("/api/admin/fcw/{final_id}/material")
async def admin_fcw_material(
    final_id: str,
    session: AsyncSession = Depends(get_session),
    _: Actor = Depends(require_fcw_admin_view),
) -> JSONResponse:
    """Q177 运营台卡片详情：六层原料包内嵌 JSON（读闸、无 attachment 头）。

    与 Q155 GET /api/fcw/{final_id}/material.json（导出下载、attachment 头、无
    query actor 闸）是同一 build_material_pack 的两个面：本口供页面内展开，过
    operations|platform_admin 读闸；只读、不触发 Guard、不写审计，未知 id 404。
    """

    fcw = await service.get_fcw(session, final_id)
    if fcw is None:
        raise HTTPException(404, f"FCW not found: {final_id}")
    pack = await material.build_material_pack(session, fcw)
    return JSONResponse(content=jsonable_encoder(pack))
