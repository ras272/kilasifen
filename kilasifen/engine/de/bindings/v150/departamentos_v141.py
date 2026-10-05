from __future__ import annotations

from enum import Enum

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


class TDepartamentos(Enum):
    """
    Código del departamento donde se realiza la transacción.

    Attributes:
        VALUE_1: CAPITAL
        VALUE_2: CONCEPCION
        VALUE_3: SAN PEDRO
        VALUE_4: CORDILLERA
        VALUE_5: GUAIRA
        VALUE_6: CAAGUAZU
        VALUE_7: CAAZAPA
        VALUE_8: ITAPUA
        VALUE_9: MISIONES
        VALUE_10: PARAGUARI
        VALUE_11: ALTO PARANA
        VALUE_12: CENTRAL
        VALUE_13: NEEMBUCU
        VALUE_14: AMAMBAY
        VALUE_15: PTE. HAYES
        VALUE_16: BOQUERON
        VALUE_17: ALTO PARAGUAY
        VALUE_18: CANINDEYU
        VALUE_19: CHACO
        VALUE_20: NUEVA ASUNCION
    """

    VALUE_1 = 1
    VALUE_2 = 2
    VALUE_3 = 3
    VALUE_4 = 4
    VALUE_5 = 5
    VALUE_6 = 6
    VALUE_7 = 7
    VALUE_8 = 8
    VALUE_9 = 9
    VALUE_10 = 10
    VALUE_11 = 11
    VALUE_12 = 12
    VALUE_13 = 13
    VALUE_14 = 14
    VALUE_15 = 15
    VALUE_16 = 16
    VALUE_17 = 17
    VALUE_18 = 18
    VALUE_19 = 19
    VALUE_20 = 20


class TDesDepartamento(Enum):
    """
    Descripción del departamento donde se realiza la transacción.
    """

    CAPITAL = "CAPITAL"
    CONCEPCION = "CONCEPCION"
    SAN_PEDRO = "SAN PEDRO"
    CORDILLERA = "CORDILLERA"
    GUAIRA = "GUAIRA"
    CAAGUAZU = "CAAGUAZU"
    CAAZAPA = "CAAZAPA"
    ITAPUA = "ITAPUA"
    MISIONES = "MISIONES"
    PARAGUARI = "PARAGUARI"
    ALTO_PARANA = "ALTO PARANA"
    CENTRAL = "CENTRAL"
    NEEMBUCU = "NEEMBUCU"
    AMAMBAY = "AMAMBAY"
    PTE_HAYES = "PTE. HAYES"
    BOQUERON = "BOQUERON"
    ALTO_PARAGUAY = "ALTO PARAGUAY"
    CANINDEYU = "CANINDEYU"
    CHACO = "CHACO"
    NUEVA_ASUNCION = "NUEVA ASUNCION"
