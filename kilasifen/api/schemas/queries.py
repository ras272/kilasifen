"""Pydantic schemas for query APIs."""

from datetime import datetime

from pydantic import BaseModel


class TaxpayerResponse(BaseModel):
    """Normalized taxpayer data returned from SIFEN."""

    ruc: str
    legal_name: str
    state_code: str | None
    state: str | None
    electronic_taxpayer: bool | None


class RucQueryResponse(BaseModel):
    """Normalized response for a RUC query."""

    queried_ruc: str
    status: str
    result_code: str | None
    result_message: str | None
    taxpayer: TaxpayerResponse | None


class DocumentQueryResponse(BaseModel):
    """Normalized response for a document query."""

    document_id: str
    cdc: str
    status: str
    result_code: str | None
    result_message: str | None
    content_xml: str | None
    processed_at: datetime | None
