"""Common API response models."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")

_CORRELATION_ID_DESCRIPTION = (
    "Identificador de la solicitud; es el mismo valor del header "
    "`X-Correlation-ID`. Conservalo en los logs del ERP y en los tickets."
)


class SuccessEnvelope(BaseModel, Generic[DataT]):
    """Respuesta exitosa: el recurso va en `data`."""

    data: DataT
    correlation_id: str = Field(description=_CORRELATION_ID_DESCRIPTION)


class Pagination(BaseModel):
    """Página devuelta por un listado."""

    limit: int = Field(description="Tamaño de página pedido.")
    offset: int = Field(description="Cantidad de elementos salteados.")
    count: int = Field(description="Cantidad de elementos de esta página.")


class ErrorPayload(BaseModel):
    """Error de la API."""

    code: str = Field(
        description=(
            "Código estable del error, por ejemplo `documents.not_found`. "
            "Decidí la recuperación con este campo y con `details`."
        )
    )
    message: str = Field(
        description=(
            "Texto orientativo en inglés, casi siempre genérico (por ejemplo "
            "«Request validation failed.»). No es estable: no lo uses para decidir."
        )
    )
    category: str = Field(
        description=(
            "Grupo del código: `authentication`, `authorization`, `validation`, "
            "`invalid_request`, `not_found`, `conflict`, `rate_limit`, "
            "`service_unavailable` o `internal`. La lista puede crecer."
        )
    )
    correlation_id: str = Field(description=_CORRELATION_ID_DESCRIPTION)
    details: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Datos propios del código. En `request.validation_failed`, "
            "`errors` lista cada problema con `loc`, `message` y `type`."
        ),
    )


class ErrorEnvelope(BaseModel):
    """Respuesta de error: el detalle va en `error`."""

    error: ErrorPayload
