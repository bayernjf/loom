import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.content.router import router as content_router
from app.core.a2a.router import router as a2a_router
from app.core.api_keys.router import router as agent_keys_router
from app.core.compliance_wordlist.router import router as wordlist_router
from app.core.config_center.broadcast import ConfigBroadcastSubscriber
from app.core.config_center.cache import config_cache
from app.core.config_center.router import router as config_router
from app.core.dashboards.router import router as dashboards_router
from app.core.db import SessionLocal, settings
from app.core.effects.router import router as effects_router
from app.core.exports.router import router as exports_router
from app.core.exports.worker import ExportWorker
from app.core.model_registry.router import router as model_registry_router
from app.core.restock.router import router as restock_router
from app.core.restock.worker import RestockWorker
from app.core.skill7.router import router as skill7_router
from app.core.sla.router import router as sla_router
from app.core.sla.runner import run_jobs
from app.core.sla.scheduler import SweepScheduler
from app.core.tenants.router import customer_router
from app.core.tenants.router import router as tenants_router
from app.core.workbench.router import router as workbench_router
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
_restock_worker: RestockWorker | None = None
_config_subscriber: ConfigBroadcastSubscriber | None = None
_export_worker: ExportWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler, _restock_worker, _config_subscriber, _export_worker
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
    if settings.restock_worker_enabled:
        _restock_worker = RestockWorker(
            SessionLocal,
            settings.restock_interval_seconds,
            settings.restock_batch_size,
        )
        await _restock_worker.start()
    if settings.export_worker_enabled:
        # Q137：导出任务消费组 worker（只读幂等，可多副本水平并行，无需 leader 锁）。
        _export_worker = ExportWorker(
            SessionLocal,
            block_ms=int(settings.export_stream_block_seconds * 1000),
        )
        await _export_worker.start()
    if settings.config_cache_broadcast_enabled:
        # Q135：多副本配置失效广播订阅者；启动失败不阻断应用（本进程 after_commit
        # 热更新仍生效，对端副本最坏重启后恢复一致）。
        try:
            _config_subscriber = ConfigBroadcastSubscriber(SessionLocal)
            await _config_subscriber.start()
        except Exception:
            logger.warning("config broadcast subscriber failed to start", exc_info=True)
            _config_subscriber = None
    try:
        yield
    finally:
        if _config_subscriber is not None:
            await _config_subscriber.stop()
            _config_subscriber = None
        if _export_worker is not None:
            await _export_worker.stop()
            _export_worker = None
        if _restock_worker is not None:
            await _restock_worker.stop()
            _restock_worker = None
        if _scheduler is not None:
            await _scheduler.stop()
            _scheduler = None


app = FastAPI(title="Loom", version="0.1.0", lifespan=lifespan)

app.include_router(intake_router)
app.include_router(modeling_router)
app.include_router(fieldpool_router)
app.include_router(wordlist_router)
app.include_router(config_router)
app.include_router(a2a_router)
app.include_router(dashboards_router)
app.include_router(model_registry_router)
app.include_router(skill7_router)
app.include_router(workbench_router)
app.include_router(sla_router)
app.include_router(restock_router)
app.include_router(agent_keys_router)
app.include_router(tenants_router)
app.include_router(customer_router)
app.include_router(atom_router)
app.include_router(pwc_router)
app.include_router(pws_router)
app.include_router(ccr_router)
app.include_router(platform_router)
app.include_router(package_router)
app.include_router(fcw_router)
app.include_router(content_router)
app.include_router(effects_router)
app.include_router(exports_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
