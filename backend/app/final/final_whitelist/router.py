"""段11 FCW 组装 REST 端点（08 M8）。

E1.1 publishFCW 是全系统 final_id 唯一出口（line 11036）：
本路由之外任何模块写 final_content_whitelists 均为协议违反。
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.final.final_whitelist import material, service
from app.final.final_whitelist.schemas import AssemblyManual, AssemblyTaskCreate

router = APIRouter(tags=["final-whitelist"])


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
    try:
        task = await service.create_task(session, body)
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
    await session.commit()
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
