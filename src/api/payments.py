"""Bulk payments endpoint draft."""

from fastapi import APIRouter, HTTPException, status

from api.schemas import BulkPaymentRequest


router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post("/payments/", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def create_payments(body: BulkPaymentRequest) -> None:
    """Validate the request body; payment processing will be added later."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Payment processing is not implemented yet",
    )
