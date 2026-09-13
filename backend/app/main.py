from fastapi import FastAPI

from app.product.product_intake.router import router as intake_router

app = FastAPI(title="Loom", version="0.1.0")

app.include_router(intake_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
