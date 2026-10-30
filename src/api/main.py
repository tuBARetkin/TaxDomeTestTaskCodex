"""FastAPI entry point."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from api.payments import router as payments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        yield
    finally:
        app.state.engine.dispose()


app = FastAPI(title="TaxDome Test Task", lifespan=lifespan)
app.include_router(payments_router)


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ok"}
