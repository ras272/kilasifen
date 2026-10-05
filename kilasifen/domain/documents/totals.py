"""Amounts of a DE: item IVA values (E7.2-E8.2), totals (F001-F099) and
the payments of ``gCamCond`` (E600-E659).

One calculator serves the API (``422`` at creation) and the XML builder
(local validation failure in the worker), so both apply exactly the same
rules. Rules in force (MT v150 of 10/09/2019 as modified by NT 01, NT 08 and
NT 13; NT 14-27 do not touch them):

Items
- E727 = E721 * E711 (1859); EA008 = (E721 - EA002 - EA004 - EA006 - EA007)
  * E711 (1853); EA009 = EA008 * E725 when D017 = 2 (1857/1858).
- EA003 = EA002 * 100 / E721, with a variation of 0.8 when the caller sends
  it (1852/1861).
- EA004 is the global discount percentage F010 applied to every item, not
  prorated and regardless of its particular discount: EA004 = F010 * E721 /
  100 (NT 01 A-1; 1860, and 1862 with a variation of 0.8). A caller-supplied
  EA004 must stay within that 0.8.
- E733: 100 for E731=1 (1904), 0 for E731=2/3 (1905), and 0 < E733 < 100 for
  E731=4 (1906), which is never defaulted. E734: 0 for E731=2/3 (1907), 5 or
  10 for E731=1/4 (1908).
- E735 = 100*EA008*E733 / (10000 + E734*E733) for E731=1/4 and 0 for 2/3
  (NT 13 §1.1 and §2.2; 1909-1911); E736 = E735 * E734/100 (1912/1913);
  E737 = 100*EA008*(100-E733) / (10000 + E734*E733) for E731=4 and 0
  otherwise (NT 13 §1.2 and §2.1; 1921).
- E735/E736/E737 keep up to 8 decimals (XSD ``tMontoBase``) instead of
  being rounded to whole guaranies one by one, and every total is the exact
  sum of what the items carry (Dto 872/2023 Art. 6 num. 5; 1913, 2367-2375).
- Amounts take at most 8 decimals (``tMontoBase``, ``tdCantProSer``) and
  exchange rates at most 4 (``tTipoCambioBase``): the XML carries exactly
  the values the totals were computed with.

Totals
- F002 = sum EA008 (E731=3) + sum E737 (E731=4); F003 = sum EA008 (E731=2);
  F004/F005 = sum EA008 (E731=1) + sum (E735 + E736) (E731=4) per rate (NT 13
  §1.3; 2353, 2355, 2357, 2359). Each one exists, even with 0, when an item
  has that affectation or rate (2352, 2354, 2356, 2358).
- F008 = F002 + F003 + F004 + F005 (2362).
- F009/F033/F034/F035 = sum of EA002/EA004/EA006/EA007 * E711; F011 = F009 +
  F033; F012 = F034 + F035 (NT 01; 2363, 2383, 2384, 2387, 2364, 2388).
- F010 = the global discount percentage, 0 without one (MT v150 p. 105:
  "Informativo, si no existe %, completar con cero").
- F013 = 0 unless the caller asks for ``multiplo_50`` (PYG only), which takes
  F008 down to a multiple of 50 Gs (MT v150 §F pp. 103 and 105: "Si no cuenta
  con redondeo completar con cero"; Dto 872/2023 Art. 6 num. 6). Foreign
  currencies are never rounded: MT §F only grants them a tolerance.
  F014 = F008 - F013 + F025 (NT 01, 2365); F025 is not used.
- F015/F016 = sum E736 and F018/F019 = sum E735 per rate; F017 = F015 + F016
  and F020 = F018 + F019; each exists when an item has that rate (2366-2377).
  F036/F037 are not informed, so F017 also meets its field definition.
- F023 = F014 * D018 (D017=1) or sum EA009 (D017=2), only when D015 != PYG
  (NT 08; 2382, 2385, 2386).
- D013 = 2 (ISC) is refused: gCamIVA must not exist then (1902) and F008
  would be F006, which the v150 XSD does not define.

Payments (:func:`resolve_payment_plan`)
- gPaConEIni is mandatory in contado (1550) and in credit with an initial
  delivery E645 (1551, MT v150 p. 81), and is not informed otherwise (1552).
- E611 dTiCamTiPag is mandatory when E609 != PYG (1556) and forbidden when
  E609 = PYG (1557): it depends on the currency of the payment, not on the
  currency of the operation. A payment without a currency is in the currency
  of the operation.
- The payments of a contado operation add up to F014, and those of the
  initial delivery to E645, within the 0.50 tolerance of MT v150 §F p. 103.
  SIFEN publishes no rejection code for it (NO DETERMINADO): the platform
  refuses an incoherent declaration instead of transmitting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, localcontext

ZERO = Decimal("0")
HUNDRED = Decimal("100")

AFFECTATION_TAXED = 1  # Gravado IVA
AFFECTATION_EXONERATED = 2  # Exonerado (Art. 100 - Ley 6380/2019)
AFFECTATION_EXEMPT = 3  # Exento
AFFECTATION_PARTIAL = 4  # Gravado parcial (Grav- Exento)
AFFECTATION_CODE_BY_NAME = {
    "gravado": AFFECTATION_TAXED,
    "exonerado": AFFECTATION_EXONERATED,
    "exento": AFFECTATION_EXEMPT,
    "gravado_parcial": AFFECTATION_PARTIAL,
}
TAX_RATES = frozenset({5, 10})
#: D013 iTImp 2 (ISC): the typed contracts cannot express it (1902, F006).
TAX_TYPE_ISC = 2

ROUNDING_NONE = "ninguno"
ROUNDING_MULTIPLE_OF_50 = "multiplo_50"
ROUNDING_MODES = frozenset({ROUNDING_NONE, ROUNDING_MULTIPLE_OF_50})

CASH = 1  # E601 Contado
CREDIT = 2  # E601 Credito
GUARANI = "PYG"

#: NT 01 (1862) and MT v150 1861: EA004 and EA003 may vary by up to 0.8.
DISCOUNT_VARIATION = Decimal("0.8")
#: MT v150 §F p. 103: calculations with decimals accept 50 cents up or down.
PAYMENT_TOLERANCE = Decimal("0.50")
#: MT v150 §F p. 103: rounding "aplica a multiplos de 50 guaranies".
ROUNDING_STEP = Decimal("50")

_AMOUNT_PLACES = 8  # tMontoBase, tdCantProSer, tPorcDesc8
_AMOUNT4_PLACES = 4  # tMontoBase4 (E608, E645), tdCRed (F013)
_RATE_PLACES = 4  # tTipoCambioBase (D018, E725, E611)
_AMOUNT_Q = Decimal("0.00000001")
_AMOUNT4_Q = Decimal("0.0001")
#: Wide enough for 15 integer + 8 decimal digits multiplied by percentages.
_CONTEXT = Context(prec=60, rounding=ROUND_HALF_UP)


class TotalsRuleError(ValueError):
    """The amounts of a DE break a SIFEN rule; ``code`` names it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ItemAmounts:
    """Amounts of one ``gCamItem`` (E711-E737)."""

    quantity: Decimal  # E711 dCantProSer
    unit_price: Decimal  # E721 dPUniProSer
    gross_total: Decimal  # E727 dTotBruOpeItem
    discount: Decimal  # EA002 dDescItem
    discount_percentage: Decimal | None  # EA003 dPorcDesIt
    global_discount: Decimal  # EA004 dDescGloItem
    advance: Decimal  # EA006 dAntPreUniIt
    global_advance: Decimal  # EA007 dAntGloPreUniIt
    total: Decimal  # EA008 dTotOpeItem
    exchange_rate: Decimal | None  # E725 dTiCamIt (D017 = 2)
    total_guaranies: Decimal | None  # EA009 dTotOpeGs (D017 = 2)
    affectation: int  # E731 iAfecIVA
    proportion: Decimal  # E733 dPropIVA
    rate: int  # E734 dTasaIVA
    taxable_base: Decimal  # E735 dBasGravIVA
    tax: Decimal  # E736 dLiqIVAItem
    exempt_base: Decimal  # E737 dBasExe


@dataclass(frozen=True, slots=True)
class DocumentTotals:
    """``gTotSub`` (F002-F023); ``None`` means the field is not informed."""

    exempt_subtotal: Decimal | None  # F002 dSubExe
    exonerated_subtotal: Decimal | None  # F003 dSubExo
    subtotal_5: Decimal | None  # F004 dSub5
    subtotal_10: Decimal | None  # F005 dSub10
    total: Decimal  # F008 dTotOpe
    discount_total: Decimal  # F009 dTotDesc
    global_discount_total: Decimal  # F033 dTotDescGlotem
    advance_total: Decimal  # F034 dTotAntItem
    global_advance_total: Decimal  # F035 dTotAnt
    global_discount_percentage: Decimal  # F010 dPorcDescTotal
    discounts: Decimal  # F011 dDescTotal
    advances: Decimal  # F012 dAnticipo
    rounding: Decimal  # F013 dRedon
    net_total: Decimal  # F014 dTotGralOpe
    tax_5: Decimal | None  # F015 dIVA5
    tax_10: Decimal | None  # F016 dIVA10
    total_tax: Decimal | None  # F017 dTotIVA
    base_5: Decimal | None  # F018 dBaseGrav5
    base_10: Decimal | None  # F019 dBaseGrav10
    total_base: Decimal | None  # F020 dTBasGraIVA
    total_guaranies: Decimal | None  # F023 dTotalGs


@dataclass(frozen=True, slots=True)
class DocumentAmounts:
    """Currency data, items and totals of one DE."""

    currency: str  # D015 cMoneOpe
    exchange_condition: int | None  # D017 dCondTiCam
    exchange_rate: Decimal | None  # D018 dTiCam
    items: tuple[ItemAmounts, ...]
    totals: DocumentTotals


@dataclass(frozen=True, slots=True)
class PaymentForm:
    """One ``gPaConEIni`` (E606-E611); ``form`` keeps the caller's details."""

    form: dict
    amount: Decimal  # E608 dMonTiPag
    currency: str  # E609 cMoneTiPag
    exchange_rate: Decimal | None  # E611 dTiCamTiPag, only when E609 != PYG


@dataclass(frozen=True, slots=True)
class PaymentPlan:
    """``gCamCond`` (E601-E645): contado or credito and its payments."""

    condition: int  # E601 iCondOpe
    forms: tuple[PaymentForm, ...]  # gPaConEIni, in order
    credit: dict | None  # source of gPagCred (E640)
    initial_delivery: Decimal | None  # E645 dMonEnt


def compute_document_amounts(typed_payload: dict) -> DocumentAmounts:
    """Compute every item and total amount of a typed DE payload."""

    _reject_isc(typed_payload)
    currency = (_text(typed_payload.get("moneda")) or GUARANI).upper()
    exchange_condition = _optional_int(
        typed_payload.get("condicion_tipo_cambio"),
        code="documents.currency.condicion_tipo_cambio_invalid",
    )
    exchange_rate = _exchange_rate(
        typed_payload.get("tipo_cambio"), code="documents.currency.tipo_cambio_invalid"
    )
    global_percentage = _global_discount_percentage(typed_payload)
    rounding_mode = _rounding_mode(typed_payload, currency=currency)

    raw_items = [
        item for item in typed_payload.get("items") or [] if isinstance(item, dict)
    ]
    if not raw_items:
        raise TotalsRuleError("documents.items.required")
    with localcontext(_CONTEXT):
        items = tuple(
            _compute_item(
                item,
                global_percentage=global_percentage,
                per_item_exchange=currency != GUARANI and exchange_condition == 2,
            )
            for item in raw_items
        )
        totals = _compute_totals(
            items,
            global_percentage=global_percentage,
            rounding_mode=rounding_mode,
            currency=currency,
            exchange_condition=exchange_condition,
            exchange_rate=exchange_rate,
        )
    return DocumentAmounts(
        currency=currency,
        exchange_condition=exchange_condition,
        exchange_rate=exchange_rate,
        items=items,
        totals=totals,
    )


def resolve_payment_plan(typed_payload: dict, amounts: DocumentAmounts) -> PaymentPlan:
    """Resolve ``gCamCond`` and check its payments against the totals."""

    condition_payload = _condition_payload(typed_payload)
    condition = _code(
        _first(condition_payload, "tipo", "iCondOpe", "condicion_operacion"),
        mapping={"contado": CASH, "credito": CREDIT},
        default=CASH,
        allowed=(CASH, CREDIT),
        code="documents.condicion_operacion.tipo_invalid",
    )
    raw_forms = condition_payload.get("formas_pago")
    forms_given = isinstance(raw_forms, list) and bool(raw_forms)
    net_total = amounts.totals.net_total

    if condition == CASH:
        if not forms_given:
            # A contado operation without forms is paid in cash for F014.
            raw_forms = [
                {
                    "tipo": 1,
                    "monto": str(_quantize4(net_total)),
                    "moneda": amounts.currency,
                }
            ]
        forms = _resolve_forms(raw_forms, amounts=amounts, default_amount=net_total)
        _require_payments_cover(
            forms,
            target=net_total,
            amounts=amounts,
            code="documents.condicion_operacion.formas_pago.total_mismatch",
        )
        return PaymentPlan(
            condition=CASH, forms=forms, credit=None, initial_delivery=None
        )

    credit = condition_payload.get("credito")
    if not isinstance(credit, dict):
        credit = condition_payload
    initial_delivery = _optional_decimal(
        _first(credit, "monto_entrega_inicial", "dMonEnt"),
        code="documents.condicion_operacion.credito.monto_entrega_inicial_invalid",
    )
    if initial_delivery is None:
        if forms_given:
            # 1552: without E645 a credit operation informs no gPaConEIni.
            raise TotalsRuleError(
                "documents.condicion_operacion.formas_pago_not_allowed"
            )
        return PaymentPlan(
            condition=CREDIT, forms=(), credit=credit, initial_delivery=None
        )
    if initial_delivery <= ZERO or not _has_places(initial_delivery, _AMOUNT4_PLACES):
        raise TotalsRuleError(
            "documents.condicion_operacion.credito.monto_entrega_inicial_invalid"
        )
    if not forms_given:
        # 1551: the initial delivery goes with the forms it was paid with.
        raise TotalsRuleError(
            "documents.condicion_operacion.credito.formas_pago_required"
        )
    forms = _resolve_forms(raw_forms, amounts=amounts, default_amount=initial_delivery)
    _require_payments_cover(
        forms,
        target=initial_delivery,
        amounts=amounts,
        code="documents.condicion_operacion.credito.formas_pago_mismatch",
    )
    return PaymentPlan(
        condition=CREDIT,
        forms=forms,
        credit=credit,
        initial_delivery=initial_delivery,
    )


def _compute_item(
    item: dict,
    *,
    global_percentage: Decimal,
    per_item_exchange: bool,
) -> ItemAmounts:
    quantity = _amount(
        _first(item, "cantidad", "dCantProSer"),
        code="documents.items.cantidad_invalid",
        required=True,
    )
    if quantity <= ZERO:
        raise TotalsRuleError("documents.items.cantidad_invalid")
    unit_price = _amount(
        _first(item, "precio_unitario", "precioUnitario", "dPUniProSer"),
        code="documents.items.precio_unitario_invalid",
        required=True,
    )
    discount = _amount(
        _first(item, "descuento_particular", "dDescItem"),
        code="documents.items.descuento_particular_invalid",
    )
    advance = _amount(
        _first(item, "anticipo_particular", "dAntPreUniIt"),
        code="documents.items.anticipo_particular_invalid",
    )
    global_advance = _amount(
        _first(item, "anticipo_global", "dAntGloPreUniIt"),
        code="documents.items.anticipo_global_invalid",
    )
    global_discount = _item_global_discount(
        item, unit_price=unit_price, global_percentage=global_percentage
    )
    net_unit = unit_price - discount - global_discount - advance - global_advance
    if net_unit < ZERO:
        raise TotalsRuleError("documents.items.net_unit_negative")

    total = _quantize(net_unit * quantity)
    affectation = _item_affectation(item)
    proportion = _item_proportion(item, affectation=affectation)
    rate = _item_rate(item, affectation=affectation)
    taxable_base, tax, exempt_base = _item_taxes(
        total, affectation=affectation, proportion=proportion, rate=rate
    )

    exchange_rate = None
    total_guaranies = None
    if per_item_exchange:
        exchange_rate = _exchange_rate(
            _first(item, "tipo_cambio_item", "dTiCamIt"),
            code="documents.items.tipo_cambio_item_invalid",
        )
        if exchange_rate is None:
            # 1854: D017 = 2 needs E725 in every item.
            raise TotalsRuleError("documents.items.tipo_cambio_item_required")
        total_guaranies = _quantize(total * exchange_rate)  # EA009 (1858)

    return ItemAmounts(
        quantity=quantity,
        unit_price=unit_price,
        gross_total=_quantize(unit_price * quantity),
        discount=discount,
        discount_percentage=_item_discount_percentage(
            item, unit_price=unit_price, discount=discount
        ),
        global_discount=global_discount,
        advance=advance,
        global_advance=global_advance,
        total=total,
        exchange_rate=exchange_rate,
        total_guaranies=total_guaranies,
        affectation=affectation,
        proportion=proportion,
        rate=rate,
        taxable_base=taxable_base,
        tax=tax,
        exempt_base=exempt_base,
    )


def _item_taxes(
    total: Decimal, *, affectation: int, proportion: Decimal, rate: int
) -> tuple[Decimal, Decimal, Decimal]:
    """E735, E736 and E737 of one item (NT 13 §1.1-§1.2, MT 1912/1913)."""

    if affectation in (AFFECTATION_EXONERATED, AFFECTATION_EXEMPT):
        return ZERO, ZERO, ZERO
    rate_decimal = Decimal(rate)
    denominator = Decimal("10000") + rate_decimal * proportion
    taxable_base = _quantize(HUNDRED * total * proportion / denominator)
    # E736 = E735 * E734 / 100 on the E735 actually written (1913).
    tax = _quantize(taxable_base * rate_decimal / HUNDRED)
    if affectation == AFFECTATION_TAXED:
        return taxable_base, tax, ZERO
    # E737 = 100*EA008*(100-E733)/(10000+E734*E733) equals EA008 - E735 - E736
    # algebraically. Taking the remainder keeps E735 + E736 + E737 = EA008, so
    # F008 is exactly the sum of EA008 (no 114999.99999999 for 115000), and
    # it differs from the formula by less than 1e-8, far inside the 0.50
    # tolerance of MT v150 §F p. 103 for calculations with decimals.
    exempt_base = max(total - taxable_base - tax, ZERO)
    return taxable_base, tax, exempt_base


def _compute_totals(
    items: tuple[ItemAmounts, ...],
    *,
    global_percentage: Decimal,
    rounding_mode: str,
    currency: str,
    exchange_condition: int | None,
    exchange_rate: Decimal | None,
) -> DocumentTotals:
    def informed(selected: list[Decimal]) -> Decimal | None:
        # 2352-2376: a subtotal exists, even with 0, once an item needs it.
        return sum(selected, ZERO) if selected else None

    def with_rate(rate: int) -> list[ItemAmounts]:
        return [
            item
            for item in items
            if item.affectation in (AFFECTATION_TAXED, AFFECTATION_PARTIAL)
            and item.rate == rate
        ]

    exempt_subtotal = informed(
        [item.total for item in items if item.affectation == AFFECTATION_EXEMPT]
        + [
            item.exempt_base
            for item in items
            if item.affectation == AFFECTATION_PARTIAL
        ]
    )
    exonerated_subtotal = informed(
        [item.total for item in items if item.affectation == AFFECTATION_EXONERATED]
    )
    subtotal_5 = informed([_taxed_part(item) for item in with_rate(5)])
    subtotal_10 = informed([_taxed_part(item) for item in with_rate(10)])
    total = sum(
        (
            value or ZERO
            for value in (exempt_subtotal, exonerated_subtotal, subtotal_5, subtotal_10)
        ),
        ZERO,
    )

    tax_5 = informed([item.tax for item in with_rate(5)])
    tax_10 = informed([item.tax for item in with_rate(10)])
    base_5 = informed([item.taxable_base for item in with_rate(5)])
    base_10 = informed([item.taxable_base for item in with_rate(10)])

    discount_total = _sum_per_quantity(items, "discount")
    global_discount_total = _sum_per_quantity(items, "global_discount")
    advance_total = _sum_per_quantity(items, "advance")
    global_advance_total = _sum_per_quantity(items, "global_advance")

    rounding = _rounding(total, mode=rounding_mode)
    net_total = total - rounding
    return DocumentTotals(
        exempt_subtotal=exempt_subtotal,
        exonerated_subtotal=exonerated_subtotal,
        subtotal_5=subtotal_5,
        subtotal_10=subtotal_10,
        total=total,
        discount_total=discount_total,
        global_discount_total=global_discount_total,
        advance_total=advance_total,
        global_advance_total=global_advance_total,
        global_discount_percentage=global_percentage,
        discounts=discount_total + global_discount_total,
        advances=advance_total + global_advance_total,
        rounding=rounding,
        net_total=net_total,
        tax_5=tax_5,
        tax_10=tax_10,
        total_tax=_sum_informed(tax_5, tax_10),
        base_5=base_5,
        base_10=base_10,
        total_base=_sum_informed(base_5, base_10),
        total_guaranies=_total_guaranies(
            items,
            net_total=net_total,
            currency=currency,
            exchange_condition=exchange_condition,
            exchange_rate=exchange_rate,
        ),
    )


def _taxed_part(item: ItemAmounts) -> Decimal:
    """Share of an item in F004/F005: EA008, or E735 + E736 if partial."""

    if item.affectation == AFFECTATION_PARTIAL:
        return item.taxable_base + item.tax
    return item.total


def _sum_per_quantity(items: tuple[ItemAmounts, ...], attribute: str) -> Decimal:
    return sum(
        (_quantize(getattr(item, attribute) * item.quantity) for item in items), ZERO
    )


def _sum_informed(first: Decimal | None, second: Decimal | None) -> Decimal | None:
    if first is None and second is None:
        return None
    return (first or ZERO) + (second or ZERO)


def _rounding(total: Decimal, *, mode: str) -> Decimal:
    """F013 dRedon over F008 (MT v150 §F pp. 103/105; Dto 872/2023 Art. 6).

    F014 is then F008 - F013 exactly (2365). ``tdCRed`` admits 4 decimals, so
    a longer remainder is written to 4 decimals and F014 keeps the rest,
    within the 0.50 tolerance of MT §F p. 103.
    """

    if mode == ROUNDING_NONE or total == ZERO:
        return ZERO
    if total < ROUNDING_STEP:
        # Rounding down would leave a document of value 0 for a sale with
        # value (R3 §4.1): refused instead of emitted.
        raise TotalsRuleError("documents.redondeo.total_below_50")
    rounded = (total / ROUNDING_STEP).to_integral_value(ROUND_DOWN) * ROUNDING_STEP
    return _quantize4(total - rounded)


def _total_guaranies(
    items: tuple[ItemAmounts, ...],
    *,
    net_total: Decimal,
    currency: str,
    exchange_condition: int | None,
    exchange_rate: Decimal | None,
) -> Decimal | None:
    """F023 (NT 08 §1.2): F014 * D018, or the sum of EA009 with D017 = 2."""

    if currency == GUARANI:
        return None
    if exchange_condition == 1 and exchange_rate is not None:
        return _quantize(net_total * exchange_rate)
    if exchange_condition == 2:
        return sum((item.total_guaranies or ZERO for item in items), ZERO)
    return None


def _item_global_discount(
    item: dict, *, unit_price: Decimal, global_percentage: Decimal
) -> Decimal:
    """EA004 = F010 * E721 / 100 (NT 01 A-1), checked against 1862."""

    expected = _quantize(global_percentage * unit_price / HUNDRED)
    provided = _amount(
        _first(item, "descuento_global", "dDescGloItem"),
        code="documents.items.descuento_global_invalid",
        default=None,
    )
    if provided is None:
        return expected
    if abs(provided - expected) > DISCOUNT_VARIATION:
        raise TotalsRuleError("documents.items.descuento_global_mismatch")
    return provided


def _item_discount_percentage(
    item: dict, *, unit_price: Decimal, discount: Decimal
) -> Decimal | None:
    """EA003 dPorcDesIt = EA002 * 100 / E721 (1852), checked against 1861."""

    expected = (
        _quantize(discount * HUNDRED / unit_price) if unit_price > ZERO else ZERO
    )
    provided = _amount(
        _first(item, "porcentaje_descuento_particular", "dPorcDesIt"),
        code="documents.items.porcentaje_descuento_particular_invalid",
        default=None,
    )
    if provided is not None:
        if provided > HUNDRED:
            raise TotalsRuleError(
                "documents.items.porcentaje_descuento_particular_invalid"
            )
        if abs(provided - expected) > DISCOUNT_VARIATION:
            raise TotalsRuleError(
                "documents.items.porcentaje_descuento_particular_mismatch"
            )
        return provided
    if discount > ZERO:
        return expected
    return None


def _item_affectation(item: dict) -> int:
    if item.get("afectacion") is None and item.get("iAfecIVA") is None:
        # Legacy items carry only a rate: 5/10 are taxed, 0 is exempt.
        legacy_rate = _optional_int(
            _first(item, "iva", "tasa", "dTasaIVA"), code="documents.items.tasa_invalid"
        )
        if legacy_rate is None or legacy_rate in TAX_RATES:
            return AFFECTATION_TAXED
        if legacy_rate == 0:
            return AFFECTATION_EXEMPT
        raise TotalsRuleError("documents.items.tasa_invalid")
    return _code(
        _first(item, "afectacion", "iAfecIVA"),
        mapping=AFFECTATION_CODE_BY_NAME,
        default=AFFECTATION_TAXED,
        allowed=tuple(AFFECTATION_CODE_BY_NAME.values()),
        code="documents.items.afectacion_invalid",
    )


def _item_proportion(item: dict, *, affectation: int) -> Decimal:
    """E733 dPropIVA (MT v150 E733 p. 91; 1904, 1905, 1906 p. 178)."""

    provided = _amount(
        _first(item, "proporcion_gravada", "dPropIVA"),
        code="documents.items.proporcion_gravada_invalid",
        default=None,
    )
    if affectation == AFFECTATION_PARTIAL:
        if provided is None:
            raise TotalsRuleError("documents.items.proporcion_gravada_required")
        if not ZERO < provided < HUNDRED:
            raise TotalsRuleError("documents.items.proporcion_gravada_invalid")
        return provided
    expected = HUNDRED if affectation == AFFECTATION_TAXED else ZERO
    if provided is not None and provided != expected:
        raise TotalsRuleError("documents.items.proporcion_gravada_invalid")
    return expected


def _item_rate(item: dict, *, affectation: int) -> int:
    """E734 dTasaIVA: 0 for exonerated/exempt (1907), 5 or 10 otherwise (1908)."""

    rate = _optional_int(
        _first(item, "tasa", "iva", "dTasaIVA"), code="documents.items.tasa_invalid"
    )
    if affectation in (AFFECTATION_EXONERATED, AFFECTATION_EXEMPT):
        if rate not in (None, 0):
            raise TotalsRuleError("documents.items.tasa_invalid")
        return 0
    if rate is None:
        return 10
    if rate not in TAX_RATES:
        raise TotalsRuleError("documents.items.tasa_invalid")
    return rate


def _global_discount_percentage(typed_payload: dict) -> Decimal:
    """F010 dPorcDescTotal: the global percentage, 0 without one (MT p. 105)."""

    value = _amount(
        _first(typed_payload, "porcentaje_descuento_global", "dPorcDescTotal"),
        code="documents.porcentaje_descuento_global_invalid",
    )
    if value > HUNDRED:
        # XSD tPorcDesc8: 0-100 with up to 8 decimals.
        raise TotalsRuleError("documents.porcentaje_descuento_global_invalid")
    return value


def _rounding_mode(typed_payload: dict, *, currency: str) -> str:
    mode = (_text(typed_payload.get("redondeo")) or ROUNDING_NONE).lower()
    if mode not in ROUNDING_MODES:
        raise TotalsRuleError("documents.redondeo.invalid")
    if mode == ROUNDING_MULTIPLE_OF_50 and currency != GUARANI:
        # The 50 Gs rule is for guaranies; foreign currencies are never
        # rounded automatically (MT §F p. 103 only grants a tolerance).
        raise TotalsRuleError("documents.redondeo.only_pyg")
    return mode


def _reject_isc(typed_payload: dict) -> None:
    """D013 = 2 (ISC): gCamIVA must not exist (1902) and F008 = F006 (p. 104).

    The v150 XSD has no F006 ``dSubISC`` and the typed contracts carry no ISC
    data, so such a DE cannot be built truthfully.
    """

    value = _text(typed_payload.get("tipo_impuesto"))
    if value is not None and value.lower() in {str(TAX_TYPE_ISC), "isc"}:
        raise TotalsRuleError("documents.tipo_impuesto.isc_not_supported")


def _resolve_forms(
    raw_forms: list, *, amounts: DocumentAmounts, default_amount: Decimal
) -> tuple[PaymentForm, ...]:
    forms = []
    for raw in raw_forms:
        if not isinstance(raw, dict):
            raise TotalsRuleError("documents.condicion_operacion.forma_pago_invalid")
        amount = _amount(
            _first(raw, "monto", "dMonTiPag"),
            code="documents.condicion_operacion.formas_pago.monto_invalid",
            places=_AMOUNT4_PLACES,
            default=None,
        )
        if amount is None:
            amount = _quantize4(default_amount)
        currency = (
            _text(_first(raw, "moneda", "cMoneTiPag")) or amounts.currency
        ).upper()
        forms.append(
            PaymentForm(
                form=raw,
                amount=amount,
                currency=currency,
                exchange_rate=_payment_exchange_rate(
                    raw, currency=currency, amounts=amounts
                ),
            )
        )
    return tuple(forms)


def _payment_exchange_rate(
    raw: dict, *, currency: str, amounts: DocumentAmounts
) -> Decimal | None:
    """E611 dTiCamTiPag by the currency of the payment (1556/1557)."""

    provided = _exchange_rate(
        _first(raw, "tipo_cambio", "dTiCamTiPag"),
        code="documents.condicion_operacion.formas_pago.tipo_cambio_invalid",
    )
    if currency == GUARANI:
        if provided is not None:
            raise TotalsRuleError(
                "documents.condicion_operacion.formas_pago.tipo_cambio_not_allowed"
            )
        return None
    if provided is not None:
        return provided
    if (
        currency == amounts.currency
        and amounts.exchange_condition == 1
        and amounts.exchange_rate is not None
    ):
        # A payment in the currency of the operation uses its rate D018.
        return amounts.exchange_rate
    raise TotalsRuleError(
        "documents.condicion_operacion.formas_pago.tipo_cambio_required"
    )


def _require_payments_cover(
    forms: tuple[PaymentForm, ...],
    *,
    target: Decimal,
    amounts: DocumentAmounts,
    code: str,
) -> None:
    """The payments add up to ``target`` in the currency of the operation.

    A payment in another currency goes through guaranies with its E611 and,
    for a foreign operation, D018. Without D018 (D017 = 2) such a payment
    cannot be converted and the check is skipped.
    """

    paid = ZERO
    with localcontext(_CONTEXT):
        for form in forms:
            converted = _in_operation_currency(form, amounts=amounts)
            if converted is None:
                return
            paid += converted
        if abs(paid - target) > PAYMENT_TOLERANCE:
            raise TotalsRuleError(code)


def _in_operation_currency(
    form: PaymentForm, *, amounts: DocumentAmounts
) -> Decimal | None:
    if form.currency == amounts.currency:
        return form.amount
    # E611 is None only for a payment in guaranies (1557).
    in_guaranies = form.amount * (form.exchange_rate or Decimal("1"))
    if amounts.currency == GUARANI:
        return in_guaranies
    if amounts.exchange_condition == 1 and amounts.exchange_rate is not None:
        return in_guaranies / amounts.exchange_rate
    return None


def _condition_payload(typed_payload: dict) -> dict:
    for key in ("condicion_operacion", "condicion"):
        value = typed_payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_AMOUNT_Q, rounding=ROUND_HALF_UP)


def _quantize4(value: Decimal) -> Decimal:
    return value.quantize(_AMOUNT4_Q, rounding=ROUND_HALF_UP)


def _has_places(value: Decimal, places: int) -> bool:
    """Tell whether ``value`` needs at most ``places`` decimals."""

    try:
        return value == value.quantize(Decimal(1).scaleb(-places))
    except ArithmeticError:  # too many digits for the context: not an amount
        return False


def _first(data: dict, *keys: str):
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _optional_decimal(value, *, code: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TotalsRuleError(code)
    try:
        parsed = Decimal(str(value).strip())
    except ArithmeticError as exc:
        raise TotalsRuleError(code) from exc
    if not parsed.is_finite():
        raise TotalsRuleError(code)
    return parsed


_MISSING = object()


def _amount(
    value,
    *,
    code: str,
    required: bool = False,
    places: int = _AMOUNT_PLACES,
    default=_MISSING,
) -> Decimal | None:
    """A non-negative amount with at most ``places`` decimals.

    Missing values are refused when ``required``, otherwise they become
    ``default`` (0 unless given).
    """

    parsed = _optional_decimal(value, code=code)
    if parsed is None:
        if required:
            raise TotalsRuleError(code)
        return ZERO if default is _MISSING else default
    if parsed < ZERO or not _has_places(parsed, places):
        raise TotalsRuleError(code)
    return parsed


def _exchange_rate(value, *, code: str) -> Decimal | None:
    """A positive exchange rate with at most 4 decimals (``tTipoCambioBase``)."""

    parsed = _amount(value, code=code, places=_RATE_PLACES, default=None)
    if parsed is not None and parsed <= ZERO:
        raise TotalsRuleError(code)
    return parsed


def _optional_int(value, *, code: str) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise TotalsRuleError(code) from exc


def _code(
    value,
    *,
    mapping: dict[str, int],
    default: int,
    allowed: tuple[int, ...],
    code: str,
) -> int:
    text = _text(value)
    if text is None:
        return default
    if text.isdigit():
        resolved = int(text)
    else:
        resolved = mapping.get(text.lower().replace(" ", "_").replace("-", "_"))
    if resolved not in allowed:
        raise TotalsRuleError(code)
    return resolved
