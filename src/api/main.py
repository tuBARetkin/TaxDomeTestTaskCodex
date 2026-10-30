"""FastAPI entry point."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from api.payments import router as payments_router
from repositories.errors import PaymentRejected


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_engine(
        os.environ["DATABASE_URL"],
        pool_pre_ping=True,
        echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
    )
    try:
        yield
    finally:
        app.state.engine.dispose()


app = FastAPI(title="TaxDome Test Task", lifespan=lifespan)
app.include_router(payments_router)


@app.exception_handler(RequestValidationError)
async def handle_request_validation(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Pydantic preserves the original ValueError in each validation error's context.
    causes = [error.get("ctx", {}).get("error") for error in exc.errors()]
    if causes and all(isinstance(cause, PaymentRejected) for cause in causes):
        rejection = causes[0]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": {"code": rejection.code, "message": str(rejection)}},
        )
    return await request_validation_exception_handler(request, exc)


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ok"}
