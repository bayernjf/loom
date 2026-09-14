from fastapi import FastAPI

from app.core.compliance_wordlist.router import router as wordlist_router
from app.decision.compliance_center.router import router as ccr_router
from app.decision.layer_strategy.router import router as package_router
from app.platform.platform_adaptation.router import router as platform_router
from app.product.atom.router import router as atom_router
from app.product.condition.router import router as pwc_router
from app.product.fieldpool.router import router as fieldpool_router
from app.product.modeling.router import router as modeling_router
from app.product.product_intake.router import router as intake_router
from app.product.whitelist_center.router import router as pws_router

app = FastAPI(title="Loom", version="0.1.0")

app.include_router(intake_router)
app.include_router(modeling_router)
app.include_router(fieldpool_router)
app.include_router(wordlist_router)
app.include_router(atom_router)
app.include_router(pwc_router)
app.include_router(pws_router)
app.include_router(ccr_router)
app.include_router(platform_router)
app.include_router(package_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
