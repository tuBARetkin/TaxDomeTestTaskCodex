"""REST endpoint for bulk payments."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.schemas import BulkPaymentRequest
from repositories.errors import PaymentRejected
from services.payments import PaymentService

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post("/payments/", status_code=status.HTTP_201_CREATED, response_class=Response)
def create_payments(body: BulkPaymentRequest, request: Request) -> Response:
    try:
        PaymentService(request.app.state.engine).bulk_update(body)
    except PaymentRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return Response(status_code=status.HTTP_201_CREATED)
