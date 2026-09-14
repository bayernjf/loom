import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.compliance_wordlist.router import router as wordlist_router
from app.core.config_center.cache import config_cache
from app.core.config_center.router import router as config_router
from app.core.db import SessionLocal, settings
from app.core.sla.router import router as sla_router
from app.core.sla.runner import run_jobs
from app.core.sla.scheduler import SweepScheduler
from app.decision.compliance_center.router import router as ccr_router
from app.decision.layer_strategy.router import router as package_router
from app.final.final_whitelist.router import router as fcw_router
from app.platform.platform_adaptation.router import router as platform_router
from app.product.atom.router import router as atom_router
from app.product.condition.router import router as pwc_router
from app.product.fieldpool.router import router as fieldpool_router
from app.product.modeling.router import router as modeling_router
from app.product.product_intake.router import router as intake_router
from app.product.whitelist_center.router import router as pws_router

logger = logging.getLogger("loom.startup")

_scheduler: SweepScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    # M10c：启动引导配置缓存。失败不阻断启动——knob() 回落种子默认值，
    # 进程仍可健康启动，配置中心在下次发布或重启后恢复（单进程 V1）。
    try:
        async with SessionLocal() as session:
            await config_cache.reload(session)
    except Exception:
        logger.warning("config cache bootstrap failed; falling back to seed defaults", exc_info=True)
    if settings.scheduler_enabled:
        _scheduler = SweepScheduler(SessionLocal, run_jobs, settings.sweep_interval_seconds)
        await _scheduler.start()
    try:
        yield
    finally:
        if _scheduler is not None:
            await _scheduler.stop()
            _scheduler = None


app = FastAPI(title="Loom", version="0.1.0", lifespan=lifespan)

app.include_router(intake_router)
app.include_router(modeling_router)
app.include_router(fieldpool_router)
app.include_router(wordlist_router)
app.include_router(config_router)
app.include_router(sla_router)
app.include_router(atom_router)
app.include_router(pwc_router)
app.include_router(pws_router)
app.include_router(ccr_router)
app.include_router(platform_router)
app.include_router(package_router)
app.include_router(fcw_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
