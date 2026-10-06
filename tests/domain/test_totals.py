"""Item IVA, totals and payments of a DE (MT v150 + NT 01, NT 08 and NT 13)."""

from decimal import Decimal

import pytest

from kilasifen.domain.documents.totals import (
    CASH,
    CREDIT,
    TotalsRuleError,
    compute_document_amounts,
    resolve_payment_plan,
)

D = Decimal


def _item(**changes) -> dict:
    item = {
        "cantidad": "1",
        "precio_unitario": "110000",
        "afectacion": "gravado",
        "tasa": 10,
    }
    item.update(changes)
    return item


def _amounts(*items: dict, **payload):
    return compute_document_amounts({"items": list(items), **payload})


def _refused(code: str, *items: dict, **payload) -> None:
    with pytest.raises(TotalsRuleError) as raised:
        _amounts(*items, **payload)
    assert raised.value.code == code


# --- E733-E737: affectation, proportion and item IVA ------------------------


def test_taxed_item_includes_iva_in_its_total() -> None:
    item = _amounts(_item()).items[0]

    assert (item.proportion, item.rate) == (D("100"), 10)
    assert item.taxable_base == D("100000")
    assert item.tax == D("10000")
    assert item.exempt_base == 0


@pytest.mark.parametrize("affectation", ["exento", "exonerado"])
def test_exempt_and_exonerated_items_have_proportion_and_bases_zero(
    affectation: str,
) -> None:
    # 1905 (E733 = 0), 1907 (E734 = 0), 1909/1912 (E735 = E736 = 0) and
    # NT 13 §1.2 / 1921 (E737 = 0 for E731 = 2 or 3).
    item = _amounts(_item(afectacion=affectation, tasa=0, precio_unitario="20000"))
    values = item.items[0]

    assert values.proportion == 0
    assert values.rate == 0
    assert (values.taxable_base, values.tax, values.exempt_base) == (0, 0, 0)


def test_partial_item_follows_the_nt13_formulas() -> None:
    # NT 13 §1.1/§1.2: EA008 = 100000, E733 = 30, E734 = 10.
    values = _amounts(
        _item(precio_unitario="100000", afectacion="gravado_parcial",
              proporcion_gravada="30")
    ).items[0]

    # [100 * EA008 * E733] / [10000 + E734 * E733] = 3e8 / 10300 = 29126.2136...
    # written with the 2 decimals of PYG (decision F42).
    assert values.taxable_base == D("29126.21")
    # E736 = E735 * E734 / 100 on the E735 written: 2912.621 -> 2912.62.
    assert values.tax == D("2912.62")
    # [100 * EA008 * (100 - E733)] / [10000 + E734 * E733] = 7e8 / 10300 is
    # 67961.165...; E737 is the remainder 67961.17, inside the 0.50 tolerance
    # of MT v150 §F p. 103, so that E735 + E736 + E737 is exactly EA008.
    assert values.exempt_base == D("67961.17")
    assert abs(values.exempt_base - D(700_000_000) / D(10300)) <= D("0.02")
    assert values.taxable_base + values.tax + values.exempt_base == D("100000")


def test_partial_item_without_proportion_is_refused() -> None:
    # 1906 and DECISIONES F40: no default 100 for gravado parcial.
    _refused(
        "documents.items.proporcion_gravada_required",
        _item(afectacion="gravado_parcial"),
    )


@pytest.mark.parametrize("proportion", ["0", "100", "100.5"])
def test_partial_item_proportion_must_be_strictly_between_0_and_100(
    proportion: str,
) -> None:
    _refused(
        "documents.items.proporcion_gravada_invalid",
        _item(afectacion="gravado_parcial", proporcion_gravada=proportion),
    )


@pytest.mark.parametrize(
    ("affectation", "tasa", "proportion"),
    [("gravado", 10, "50"), ("exento", 0, "100"), ("exonerado", 0, "30")],
)
def test_proportion_contradicting_the_affectation_is_refused(
    affectation: str, tasa: int, proportion: str
) -> None:
    # 1904 (E731=1 -> 100) and 1905 (E731=2/3 -> 0).
    _refused(
        "documents.items.proporcion_gravada_invalid",
        _item(afectacion=affectation, tasa=tasa, proporcion_gravada=proportion),
    )


@pytest.mark.parametrize(
    ("affectation", "tasa"), [("exento", 10), ("gravado", 0), ("gravado", 7)]
)
def test_rate_contradicting_the_affectation_is_refused(
    affectation: str, tasa: int
) -> None:
    # 1907 (E731=2/3 -> 0) and 1908 (E731=1/4 -> 5 or 10).
    _refused("documents.items.tasa_invalid", _item(afectacion=affectation, tasa=tasa))


@pytest.mark.parametrize("rate", [5, 10])
def test_item_iva_is_exactly_the_base_times_the_rate(rate: int) -> None:
    # 1913: E736 = E735 * E734 / 100 on the values written. In PYG both carry
    # 2 decimals (decision F42), so they differ by half a cent at most, far
    # inside the 0.50 tolerance of MT v150 §F p. 103. With whole-guarani
    # rounding the difference reached 0.50 in 9-18 % of the amounts (R3 §3.2).
    for price in range(1, 2000):
        values = _amounts(_item(precio_unitario=str(price), tasa=rate)).items[0]
        assert values.taxable_base == values.taxable_base.quantize(D("0.01"))
        assert values.tax == values.tax.quantize(D("0.01"))
        assert abs(values.tax - values.taxable_base * rate / 100) <= D("0.005")
        assert abs(values.taxable_base + values.tax - price) <= D("0.01")


def test_foreign_currency_iva_keeps_eight_decimals() -> None:
    # Decision F42 only narrows PYG; other currencies keep the 8 decimals of
    # tMontoBase. 120.99 USD at 10 %: E735 = 120.99 / 1.1 = 109.990909...
    values = _amounts(
        _item(precio_unitario="120.99"),
        moneda="USD",
        tipo_cambio="7300",
        condicion_tipo_cambio=1,
    ).items[0]

    assert values.taxable_base == D("109.99090909")
    assert values.tax == D("10.99909091")


def test_amounts_with_more_than_eight_decimals_are_refused() -> None:
    # XSD tMontoBase / tdCantProSer: 8 decimals at most.
    _refused(
        "documents.items.precio_unitario_invalid",
        _item(precio_unitario="1.000000001"),
    )
    _refused("documents.items.cantidad_invalid", _item(cantidad="0.000000001"))


# --- F002-F020: subtotals and IVA totals ----------------------------------------


def test_subtotals_follow_nt13_with_a_partial_item() -> None:
    totals = _amounts(
        _item(precio_unitario="100000", afectacion="gravado_parcial",
              proporcion_gravada="30"),
        _item(precio_unitario="15000", afectacion="exonerado", tasa=0),
        _item(precio_unitario="20000", afectacion="exento", tasa=0),
    ).totals

    # 2353: EA008 (E731=3) + E737 (E731=4).
    assert totals.exempt_subtotal == D("20000") + D("67961.17")
    # 2355: EA008 (E731=2).
    assert totals.exonerated_subtotal == D("15000")
    # 2359: E735 + E736 (E731=4), not the whole EA008.
    assert totals.subtotal_10 == D("29126.21") + D("2912.62")
    assert totals.subtotal_5 is None
    # 2362: F008 = F002 + F003 + F004 + F005, here exactly the sum of EA008.
    assert totals.total == (
        totals.exempt_subtotal + totals.exonerated_subtotal + totals.subtotal_10
    )
    assert totals.total == D("135000")


def test_iva_totals_are_the_exact_sum_of_the_items() -> None:
    amounts = _amounts(
        _item(precio_unitario="100000"),
        _item(precio_unitario="50000", tasa=5),
        _item(precio_unitario="33333", tasa=10),
    )
    items, totals = amounts.items, amounts.totals

    assert totals.tax_10 == items[0].tax + items[2].tax  # 2369
    assert totals.tax_5 == items[1].tax  # 2367
    assert totals.total_tax == totals.tax_5 + totals.tax_10  # 2371
    assert totals.base_10 == items[0].taxable_base + items[2].taxable_base  # 2375
    assert totals.base_5 == items[1].taxable_base  # 2373
    assert totals.total_base == totals.base_5 + totals.base_10  # 2377


def test_subtotals_exist_with_zero_when_an_item_needs_them() -> None:
    # 2356/2366/2372: a 0 Gs item at 5 % still needs F004, F015 and F018.
    totals = _amounts(
        _item(precio_unitario="0", tasa=5),
        _item(precio_unitario="0", afectacion="exento", tasa=0),
        _item(precio_unitario="0", afectacion="exonerado", tasa=0),
    ).totals

    assert totals.subtotal_5 == 0
    assert totals.tax_5 == 0
    assert totals.base_5 == 0
    assert totals.total_tax == 0
    assert totals.total_base == 0
    assert totals.exempt_subtotal == 0  # 2352
    assert totals.exonerated_subtotal == 0  # 2354
    assert totals.subtotal_10 is None
    assert totals.tax_10 is None


def test_a_tiny_taxed_item_keeps_its_iva_total() -> None:
    # 2368: with E736 rounded to whole guaranies a 5 Gs item at 10 % lost F016.
    # With 2 decimals: E735 = 500/110 = 4.5454... -> 4.55; E736 = 0.455 -> 0.46.
    totals = _amounts(_item(precio_unitario="5")).totals

    assert totals.tax_10 == D("0.46")
    assert totals.total_tax == D("0.46")


def test_document_without_taxed_items_informs_no_iva_totals() -> None:
    totals = _amounts(_item(afectacion="exento", tasa=0)).totals

    assert totals.tax_5 is totals.tax_10 is totals.total_tax is None
    assert totals.base_5 is totals.base_10 is totals.total_base is None


def test_isc_tax_type_is_refused() -> None:
    # 1902: gCamIVA must not exist with D013 = 2; F008 would be F006.
    _refused("documents.tipo_impuesto.isc_not_supported", _item(), tipo_impuesto=2)
    _refused(
        "documents.tipo_impuesto.isc_not_supported", _item(), tipo_impuesto="isc"
    )


# --- EA002-EA004, F009-F012: discounts ----------------------------------------


def test_global_percentage_is_applied_to_every_unit_price() -> None:
    # NT 01 A-1: EA004 = F010 * E721 / 100, not prorated, even with a
    # particular discount.
    amounts = _amounts(
        _item(precio_unitario="90000"),
        _item(precio_unitario="70000", descuento_particular="7000"),
        porcentaje_descuento_global="10",
    )
    first, second = amounts.items
    totals = amounts.totals

    assert first.global_discount == D("9000")
    assert second.global_discount == D("7000")
    assert second.total == D("56000")  # 70000 - 7000 - 7000 (1853)
    assert totals.global_discount_percentage == D("10")  # F010
    assert totals.discount_total == D("7000")  # F009 (2363)
    assert totals.global_discount_total == D("16000")  # F033 (2383)
    assert totals.discounts == D("23000")  # F011 (2364)
    assert totals.total == D("137000")


def test_particular_discount_alone_leaves_the_global_percentage_at_zero() -> None:
    # R3 prueba B: F010 was 11.11 with EA004 = 0 (1862).
    amounts = _amounts(_item(precio_unitario="100000", descuento_particular="10000"))

    assert amounts.totals.global_discount_percentage == 0
    assert amounts.items[0].global_discount == 0
    assert amounts.items[0].discount_percentage == D("10")  # EA003 (1852)


def test_caller_global_discount_may_vary_by_up_to_0_8() -> None:
    amounts = _amounts(
        _item(precio_unitario="99999", descuento_global="10000.7"),
        porcentaje_descuento_global="10",
    )

    assert amounts.items[0].global_discount == D("10000.7")


@pytest.mark.parametrize(
    ("percentage", "provided"), [("10", "10001"), ("0", "5000")]
)
def test_caller_global_discount_off_the_formula_is_refused(
    percentage: str, provided: str
) -> None:
    # 1862: |EA004 - F010 * E721 / 100| <= 0.8.
    _refused(
        "documents.items.descuento_global_mismatch",
        _item(precio_unitario="100000", descuento_global=provided),
        porcentaje_descuento_global=percentage,
    )


def test_caller_discount_percentage_off_the_formula_is_refused() -> None:
    # 1861: EA003 = EA002 * 100 / E721 with a variation of 0.8.
    _refused(
        "documents.items.porcentaje_descuento_particular_mismatch",
        _item(
            precio_unitario="100000",
            descuento_particular="10000",
            porcentaje_descuento_particular="11",
        ),
    )
    accepted = _amounts(
        _item(
            precio_unitario="100000",
            descuento_particular="10000",
            porcentaje_descuento_particular="10.5",
        )
    )
    assert accepted.items[0].discount_percentage == D("10.5")


def test_global_percentage_outside_0_100_is_refused() -> None:
    _refused(
        "documents.porcentaje_descuento_global_invalid",
        _item(),
        porcentaje_descuento_global="100.1",
    )


def test_deductions_over_the_unit_price_are_refused() -> None:
    _refused(
        "documents.items.net_unit_negative",
        _item(precio_unitario="1000", descuento_particular="600"),
        porcentaje_descuento_global="50",
    )


def test_advances_are_totalled_per_quantity() -> None:
    totals = _amounts(
        _item(cantidad="2", precio_unitario="1000", anticipo_particular="100"),
        _item(cantidad="3", precio_unitario="1000", anticipo_global="200"),
    ).totals

    assert totals.advance_total == D("200")  # F034 (2384)
    assert totals.global_advance_total == D("600")  # F035 (2387)
    assert totals.advances == D("800")  # F012 (2388)


# --- F013/F014: rounding --------------------------------------------------------


def test_rounding_is_none_by_default() -> None:
    # MT v150 F013: "Si no cuenta con redondeo completar con cero".
    totals = _amounts(_item(precio_unitario="107437")).totals

    assert totals.rounding == 0
    assert totals.net_total == D("107437")


@pytest.mark.parametrize(
    ("total", "rounding", "net_total"),
    [("107437", "37", "107400"), ("47789", "39", "47750"), ("50000", "0", "50000")],
)
def test_multiple_of_50_follows_the_mt_examples(
    total: str, rounding: str, net_total: str
) -> None:
    # MT v150 §F p. 103 examples: 107.437 -> 107.400 and 47.789 -> 47.750.
    totals = _amounts(_item(precio_unitario=total), redondeo="multiplo_50").totals

    assert totals.rounding == D(rounding)
    assert totals.net_total == D(net_total)
    assert totals.net_total == totals.total - totals.rounding  # 2365


def test_rounding_keeps_decimals_of_a_guarani_total() -> None:
    totals = _amounts(
        _item(cantidad="333", precio_unitario="1.5"), redondeo="multiplo_50"
    ).totals

    assert totals.total == D("499.5")
    assert totals.rounding == D("49.5")
    assert totals.net_total == D("450")


def test_foreign_currency_is_never_rounded() -> None:
    _refused(
        "documents.redondeo.only_pyg",
        _item(precio_unitario="100.49"),
        moneda="USD",
        condicion_tipo_cambio=1,
        tipo_cambio="7300",
        redondeo="multiplo_50",
    )
    totals = _amounts(
        _item(precio_unitario="100.49"),
        moneda="USD",
        condicion_tipo_cambio=1,
        tipo_cambio="7300",
    ).totals
    assert totals.rounding == 0
    assert totals.net_total == D("100.49")


def test_rounding_a_total_under_50_is_refused() -> None:
    _refused(
        "documents.redondeo.total_below_50",
        _item(precio_unitario="30"),
        redondeo="multiplo_50",
    )


def test_unknown_rounding_mode_is_refused() -> None:
    _refused("documents.redondeo.invalid", _item(), redondeo="hacia_arriba")


# --- F023 and exchange rates ------------------------------------------------------


def test_total_in_guaranies_with_a_global_rate() -> None:
    # NT 08 / 2385: F023 = F014 * D018.
    totals = _amounts(
        _item(precio_unitario="120.5"),
        moneda="USD",
        condicion_tipo_cambio=1,
        tipo_cambio="7300.25",
    ).totals

    assert totals.total_guaranies == D("120.5") * D("7300.25")


def test_total_in_guaranies_with_a_rate_per_item() -> None:
    # 1858: EA009 = EA008 * E725; 2386: F023 = sum EA009.
    amounts = _amounts(
        _item(precio_unitario="10", tipo_cambio_item="7300"),
        _item(precio_unitario="20", tipo_cambio_item="7310"),
        moneda="USD",
        condicion_tipo_cambio=2,
    )

    assert [item.total_guaranies for item in amounts.items] == [
        D("73000"),
        D("146200"),
    ]
    assert amounts.totals.total_guaranies == D("219200")


def test_rate_per_item_is_required_with_condition_2() -> None:
    _refused(
        "documents.items.tipo_cambio_item_required",
        _item(precio_unitario="10"),
        moneda="USD",
        condicion_tipo_cambio=2,
    )


def test_exchange_rate_with_more_than_four_decimals_is_refused() -> None:
    # XSD tTipoCambioBase: 4 decimals; F023 must use the rate written.
    _refused(
        "documents.currency.tipo_cambio_invalid",
        _item(),
        moneda="USD",
        condicion_tipo_cambio=1,
        tipo_cambio="7300.12345",
    )


# --- gCamCond: payments -------------------------------------------------------


def _plan(payload: dict):
    return resolve_payment_plan(payload, compute_document_amounts(payload))


def _plan_refused(code: str, payload: dict) -> None:
    with pytest.raises(TotalsRuleError) as raised:
        _plan(payload)
    assert raised.value.code == code


def test_contado_without_forms_is_paid_in_cash_for_the_net_total() -> None:
    plan = _plan(
        {"items": [_item(precio_unitario="107437")], "redondeo": "multiplo_50"}
    )

    assert plan.condition == CASH
    assert [(form.amount, form.currency) for form in plan.forms] == [
        (D("107400"), "PYG")
    ]
    assert plan.forms[0].exchange_rate is None  # 1557


def test_contado_payments_must_add_up_to_the_net_total() -> None:
    payload = {
        "items": [_item(precio_unitario="100000")],
        "condicion_operacion": {
            "tipo": "contado",
            "formas_pago": [
                {"tipo": "efectivo", "monto": "60000"},
                {"tipo": "transferencia", "monto": "40000.5"},
            ],
        },
    }
    assert len(_plan(payload).forms) == 2  # within the 0.50 tolerance

    payload["condicion_operacion"]["formas_pago"][1]["monto"] = "30000"
    _plan_refused("documents.condicion_operacion.formas_pago.total_mismatch", payload)


def test_payment_rate_follows_the_currency_of_the_payment() -> None:
    # USD operation (D018 = 7300) paid partly in guaranies and partly in USD.
    plan = _plan(
        {
            "moneda": "USD",
            "condicion_tipo_cambio": 1,
            "tipo_cambio": "7300",
            "items": [_item(precio_unitario="100")],
            "condicion_operacion": {
                "tipo": "contado",
                "formas_pago": [
                    {"tipo": "efectivo", "monto": "365000", "moneda": "PYG"},
                    {"tipo": "transferencia", "monto": "50"},
                ],
            },
        }
    )

    guaranies, dollars = plan.forms
    assert (guaranies.currency, guaranies.exchange_rate) == ("PYG", None)  # 1557
    assert (dollars.currency, dollars.exchange_rate) == ("USD", D("7300"))  # 1556


def test_foreign_payment_in_a_guarani_operation_needs_its_rate() -> None:
    payload = {
        "items": [_item(precio_unitario="730000")],
        "condicion_operacion": {
            "tipo": "contado",
            "formas_pago": [{"tipo": "efectivo", "monto": "100", "moneda": "USD"}],
        },
    }
    _plan_refused(
        "documents.condicion_operacion.formas_pago.tipo_cambio_required", payload
    )

    payload["condicion_operacion"]["formas_pago"][0]["tipo_cambio"] = "7300"
    plan = _plan(payload)
    assert plan.forms[0].exchange_rate == D("7300")


def test_guarani_payment_with_a_rate_is_refused() -> None:
    # 1557: no E611 when E609 = PYG.
    _plan_refused(
        "documents.condicion_operacion.formas_pago.tipo_cambio_not_allowed",
        {
            "items": [_item()],
            "condicion_operacion": {
                "tipo": "contado",
                "formas_pago": [
                    {"tipo": "efectivo", "monto": "110000", "tipo_cambio": "1"}
                ],
            },
        },
    )


def test_operation_rate_per_item_needs_the_payment_rate() -> None:
    _plan_refused(
        "documents.condicion_operacion.formas_pago.tipo_cambio_required",
        {
            "moneda": "USD",
            "condicion_tipo_cambio": 2,
            "items": [_item(precio_unitario="10", tipo_cambio_item="7300")],
        },
    )


def test_credit_with_initial_delivery_carries_its_payments() -> None:
    plan = _plan(
        {
            "items": [_item()],
            "condicion_operacion": {
                "tipo": "credito",
                "formas_pago": [{"tipo": "efectivo", "monto": "10000"}],
                "credito": {
                    "tipo": "cuotas",
                    "monto_entrega_inicial": "10000",
                    "cuotas": [{"monto": "100000"}],
                },
            },
        }
    )

    assert plan.condition == CREDIT
    assert plan.initial_delivery == D("10000")
    assert [form.amount for form in plan.forms] == [D("10000")]


def test_credit_initial_delivery_without_payments_is_refused() -> None:
    # 1551: gPaConEIni is mandatory when E645 exists.
    _plan_refused(
        "documents.condicion_operacion.credito.formas_pago_required",
        {
            "items": [_item()],
            "condicion_operacion": {
                "tipo": "credito",
                "credito": {"tipo": "plazo", "descripcion": "30 dias",
                            "monto_entrega_inicial": "10000"},
            },
        },
    )


def test_credit_initial_delivery_payments_must_add_up_to_it() -> None:
    _plan_refused(
        "documents.condicion_operacion.credito.formas_pago_mismatch",
        {
            "items": [_item()],
            "condicion_operacion": {
                "tipo": "credito",
                "formas_pago": [{"tipo": "efectivo", "monto": "5000"}],
                "credito": {"tipo": "plazo", "descripcion": "30 dias",
                            "monto_entrega_inicial": "10000"},
            },
        },
    )


def test_credit_without_initial_delivery_takes_no_payments() -> None:
    # 1552: no gPaConEIni in credit without E645.
    payload = {
        "items": [_item()],
        "condicion_operacion": {
            "tipo": "credito",
            "credito": {"tipo": "plazo", "descripcion": "30 dias"},
        },
    }
    assert _plan(payload).forms == ()

    payload["condicion_operacion"]["formas_pago"] = [
        {"tipo": "efectivo", "monto": "110000"}
    ]
    _plan_refused("documents.condicion_operacion.formas_pago_not_allowed", payload)


def test_payment_amount_with_more_than_four_decimals_is_refused() -> None:
    # XSD tMontoBase4 (E608).
    _plan_refused(
        "documents.condicion_operacion.formas_pago.monto_invalid",
        {
            "items": [_item(precio_unitario="1.5")],
            "condicion_operacion": {
                "tipo": "contado",
                "formas_pago": [{"tipo": "efectivo", "monto": "1.50001"}],
            },
        },
    )
