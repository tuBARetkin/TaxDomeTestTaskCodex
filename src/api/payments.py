"""REST endpoint for bulk payments."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from api.schemas import BulkPaymentRequest
from services.payments import PaymentInstruction, PaymentRejected, PaymentService


router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post("/payments/", status_code=status.HTTP_201_CREATED, response_class=Response)
def create_payments(body: BulkPaymentRequest, request: Request) -> Response:
    payments = [
        PaymentInstruction(
            amount=item.amount,
            payee_firm_uuid=str(item.payee_firm_uuid),
            description=item.description,
        )
        for item in body.payments
    ]
    try:
        PaymentService(request.app.state.engine).bulk_update(str(body.payer_firm_uuid), payments)
    except PaymentRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return Response(status_code=status.HTTP_201_CREATED)
