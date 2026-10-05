"""gDatRec rules in force (MT v150 + NT 03, 10, 23, 24, 26)."""

from decimal import Decimal

import pytest

from kilasifen.domain.documents.receiver import (
    INNOMINADO_NAME,
    ReceiverRuleError,
    innominado_limit_error,
    resolve_receiver,
)
from kilasifen.engine.sdk.catalogos import descripcion_departamento, descripcion_pais
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv

_TAXPAYER = {
    "naturaleza": 1,
    "tipo_operacion": 1,
    "tipo_contribuyente": 2,
    "ruc": "80025298-5",
    "razon_social": "CLIENTE FICTICIO SA",
}
_CONSUMER = {
    "naturaleza": 2,
    "tipo_operacion": 2,
    "tipo_documento_identidad": 1,
    "numero_documento_identidad": "1234567",
    "nombre": "PERSONA FICTICIA",
}
_OVER_LIMIT = "documents.cliente.innominado_over_limit"
_INNOMINADO = {"naturaleza": 2, "tipo_operacion": 2, "tipo_documento_identidad": 5}
_FOREIGN = {
    "naturaleza": 2,
    "tipo_operacion": 4,
    "tipo_documento_identidad": 2,
    "numero_documento_identidad": "X1234567",
    "nombre": "FOREIGN CUSTOMER LLC",
    "pais_codigo": "ARG",
    "direccion": "AV. FICTICIA",
    "numero_casa": "100",
}


def _resolve(cliente: dict, document_type: int = 1):
    return resolve_receiver(
        cliente,
        document_type=document_type,
        country_description=descripcion_pais,
        department_description=descripcion_departamento,
        mod11_dv=calculate_mod11_dv,
    )


def _code(cliente: dict, document_type: int = 1) -> str:
    with pytest.raises(ReceiverRuleError) as raised:
        _resolve(cliente, document_type)
    return raised.value.code


def test_taxpayer_keeps_the_declared_type_and_a_valid_dv() -> None:
    receiver = _resolve(_TAXPAYER)

    assert (receiver.taxpayer_type, receiver.ruc, receiver.dv) == (2, "80025298", "5")
    assert (receiver.country_code, receiver.country_description) == ("PRY", "Paraguay")


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"tipo_contribuyente": None}, "documents.cliente.tipo_contribuyente_required"),
        ({"ruc": "80025298"}, "documents.cliente.dv_required"),  # D207
        ({"ruc": "80025298-4"}, "documents.cliente.dv_mismatch"),  # 1309
        ({"ruc": "80025298", "dv": "4"}, "documents.cliente.dv_mismatch"),
    ],
)
def test_taxpayer_identity_is_mandatory_and_never_defaulted(
    changes: dict, code: str
) -> None:
    assert _code({**_TAXPAYER, **changes}) == code


@pytest.mark.parametrize("operation_type", [1, 3])
def test_non_taxpayer_only_in_b2c_or_b2f(operation_type: int) -> None:
    # 1300 (NT 10 §2.1)
    cliente = {**_CONSUMER, "tipo_operacion": operation_type}

    assert _code(cliente) == "documents.cliente.tipo_operacion_not_allowed"


def test_b2f_requires_a_foreign_country_and_an_address() -> None:
    receiver = _resolve(_FOREIGN)

    assert (receiver.country_code, receiver.country_description) == (
        "ARG",
        "Argentina",
    )
    # NT 23 1335: the identity document is informed in B2F as well.
    assert (receiver.id_type, receiver.id_number) == (2, "X1234567")
    assert receiver.address.street == "AV. FICTICIA"
    assert receiver.address.department_code is None


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"pais_codigo": "PRY"}, "documents.cliente.pais_inconsistent_with_operation"),
        ({"pais_descripcion": "Brasil"}, "documents.cliente.pais_descripcion_mismatch"),
        ({"pais_codigo": "XXX"}, "documents.cliente.pais_unknown"),
        ({"direccion": None}, "documents.cliente.direccion_required"),  # 1318
        (
            {"departamento": 1, "ciudad": 1, "descripcion_ciudad": "ASUNCION"},
            "documents.cliente.ubicacion_not_allowed_for_b2f",  # NT 03
        ),
        (
            {"numero_documento_identidad": None},
            "documents.cliente.numero_documento_identidad_required",
        ),
    ],
)
def test_b2f_rules(changes: dict, code: str) -> None:
    assert _code({**_FOREIGN, **changes}) == code


def test_domestic_operation_with_a_foreign_country_is_rejected() -> None:
    # 1320: D202 != 4 goes with cPaisRec = PRY.
    assert _code({**_TAXPAYER, "pais_codigo": "ARG"}) == (
        "documents.cliente.pais_inconsistent_with_operation"
    )


def test_innominado_is_forced_to_zero_and_sin_nombre() -> None:
    receiver = _resolve({**_INNOMINADO, "nombre": "CONSUMIDOR FINAL"})

    assert receiver.is_innominado
    assert receiver.id_type_description == "Innominado"
    assert receiver.id_number == "0"
    assert receiver.name == INNOMINADO_NAME


def test_innominado_only_in_b2c() -> None:
    # 1333 (NT 23): the innominado receiver of a B2F operation is refused.
    cliente = {
        **_INNOMINADO,
        "tipo_operacion": 4,
        "pais_codigo": "ARG",
        "direccion": "AV. FICTICIA",
        "numero_casa": "1",
    }

    assert _code(cliente) == "documents.cliente.innominado_requires_b2c"


@pytest.mark.parametrize("document_type", [5, 6, 7])
def test_innominado_never_in_credit_debit_or_remission_notes(
    document_type: int,
) -> None:
    # 1331 (NT 23)
    code = _code(_INNOMINADO, document_type)

    assert code == "documents.cliente.innominado_not_allowed"


def test_other_id_type_needs_its_real_description() -> None:
    cliente = {**_CONSUMER, "tipo_documento_identidad": 9}

    assert _code(cliente) == "documents.cliente.descripcion_tipo_documento_required"
    receiver = _resolve(
        {**cliente, "descripcion_tipo_documento": "Licencia de conducir"}
    )
    assert receiver.id_type_description == "Licencia de conducir"


def test_name_is_required_without_a_default() -> None:
    assert _code({**_TAXPAYER, "razon_social": None}) == (
        "documents.cliente.nombre_required"
    )


def test_b2c_address_is_optional() -> None:
    assert _resolve(_CONSUMER).address is None


def test_domestic_address_requires_department_and_city() -> None:
    cliente = {**_TAXPAYER, "direccion": "CALLE FICTICIA", "numero_casa": "12"}

    assert _code(cliente) == "documents.cliente.departamento_ciudad_required"

    receiver = _resolve(
        {**cliente, "departamento": 12, "ciudad": 5, "descripcion_ciudad": "CIUDAD"}
    )
    assert receiver.address.department_description == "CENTRAL"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"numero_casa": None}, "documents.cliente.numero_casa_required"),  # 1330
        ({"departamento": 99}, "documents.cliente.departamento_unknown"),
        (
            {"descripcion_departamento": "CENTRAL"},
            "documents.cliente.descripcion_departamento_mismatch",
        ),
        ({"distrito": 3}, "documents.cliente.distrito_incomplete"),
        ({"descripcion_ciudad": None}, "documents.cliente.ciudad_incomplete"),
    ],
)
def test_domestic_address_consistency(changes: dict, code: str) -> None:
    cliente = {
        **_TAXPAYER,
        "direccion": "CALLE FICTICIA",
        "numero_casa": "12",
        "departamento": 1,
        "ciudad": 1,
        "descripcion_ciudad": "ASUNCION (DISTRITO)",
        **changes,
    }

    assert _code(cliente) == code


@pytest.mark.parametrize(
    ("currency", "total", "total_gs", "transaction", "expected"),
    [
        ("PYG", Decimal("6999999"), None, 1, None),
        ("PYG", Decimal("7000000"), None, 1, _OVER_LIMIT),
        ("PYG", Decimal("9000000"), None, 13, None),  # medical samples
        ("USD", Decimal("1000"), Decimal("7000000"), 1, _OVER_LIMIT),
        ("USD", Decimal("1000"), Decimal("6999999"), 1, None),
    ],
)
def test_innominado_limit_of_nt_24(currency, total, total_gs, transaction, expected):
    # 1321 (NT 24): >= 7.000.000 on F014 (PYG) or F023 (other currency).
    receiver = _resolve(_INNOMINADO)

    assert (
        innominado_limit_error(
            receiver,
            transaction_type=transaction,
            currency=currency,
            total_operation=total,
            total_guaranies=total_gs,
        )
        == expected
    )


def test_identified_consumer_has_no_limit() -> None:
    receiver = _resolve(_CONSUMER)

    assert (
        innominado_limit_error(
            receiver,
            transaction_type=1,
            currency="PYG",
            total_operation=Decimal("90000000"),
            total_guaranies=None,
        )
        is None
    )
