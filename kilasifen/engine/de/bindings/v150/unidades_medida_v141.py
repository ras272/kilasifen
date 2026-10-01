from __future__ import annotations

from enum import Enum

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


class TcUniMed(Enum):
    """
    Attributes:
        VALUE_87: Metros - m
        VALUE_2366: Costo Por Mil - CPM
        VALUE_2329: Unidad Internacional - UI
        VALUE_110: Metros cúbicos - M3
        VALUE_77: Unidad - UNI
        VALUE_86: Gramos - g
        VALUE_89: Litros - LT
        VALUE_90: Miligramos - MG
        VALUE_91: Centimetros - CM
        VALUE_92: Centimetros cuadrados - CM2
        VALUE_93: Centimetros cubicos - CM3
        VALUE_94: Pulgadas - PUL
        VALUE_96: Milímetros cuadrados - MM2
        VALUE_79: Kilogramos s/ metro cuadrado - kg/m2
        VALUE_97: Año - AA
        VALUE_98: Mes - ME
        VALUE_99: Tonelada - TN
        VALUE_100: Hora - Hs
        VALUE_101: Minuto - Mi
        VALUE_104: Determinación - DET
        VALUE_103: Yardas - Ya
        VALUE_108: Metros - MT
        VALUE_109: Metros cuadrados - M2
        VALUE_95: Milímetros - MM
        VALUE_666: Segundo - Se
        VALUE_102: Día - Di
        VALUE_83: Kilogramos - kg
        VALUE_88: Mililitros - ML
        VALUE_625: Kilómetros - Km
        VALUE_660: Metro lineal - ml
        VALUE_885: Unidad Medida Global - GL
        VALUE_891: Por Milaje - pm
        VALUE_869: Hectáreas - ha
        VALUE_569: Ración - ración
        VALUE_111: Bovinas - 4A
        VALUE_112: Curie - Ci
        VALUE_113: Docena - DOC
        VALUE_114: Galones (US) (3,7843 LT) - GLL
        VALUE_115: Gruesas - GRO
        VALUE_116: Kilogramo Bruto - E4
        VALUE_117: Kits - KT
        VALUE_118: Microcurie - M5
        VALUE_119: Milicurie - MCU
        VALUE_120: Millar - MIL
        VALUE_121: Par - PAR
        VALUE_122: Pies - FOT
        VALUE_123: Pies Cuadradas - FTK
        VALUE_124: Piezas - PCE
        VALUE_125: Quilate - KLT
        VALUE_126: Resmas - RM
        VALUE_127: Rollos - RO
        VALUE_128: 1000 Kilowatt Hora - kWh
        VALUE_129: Mazos - U(JGO)
        VALUE_130: Tambores - DR
        VALUE_131: Caja - BX
        VALUE_132: Juego - SET
        VALUE_133: Paquete - PK
        VALUE_134: Bolsa - BG
        VALUE_135: Docena Par - DPC
        VALUE_136: Pote - JR
        VALUE_137: Fardos - BL
        VALUE_138: Bulto - AB
        VALUE_139: Cesta - BK
        VALUE_140: Peso Base - BW
    """

    VALUE_87 = 87
    VALUE_2366 = 2366
    VALUE_2329 = 2329
    VALUE_110 = 110
    VALUE_77 = 77
    VALUE_86 = 86
    VALUE_89 = 89
    VALUE_90 = 90
    VALUE_91 = 91
    VALUE_92 = 92
    VALUE_93 = 93
    VALUE_94 = 94
    VALUE_96 = 96
    VALUE_79 = 79
    VALUE_97 = 97
    VALUE_98 = 98
    VALUE_99 = 99
    VALUE_100 = 100
    VALUE_101 = 101
    VALUE_104 = 104
    VALUE_103 = 103
    VALUE_108 = 108
    VALUE_109 = 109
    VALUE_95 = 95
    VALUE_666 = 666
    VALUE_102 = 102
    VALUE_83 = 83
    VALUE_88 = 88
    VALUE_625 = 625
    VALUE_660 = 660
    VALUE_885 = 885
    VALUE_891 = 891
    VALUE_869 = 869
    VALUE_569 = 569
    VALUE_111 = 111
    VALUE_112 = 112
    VALUE_113 = 113
    VALUE_114 = 114
    VALUE_115 = 115
    VALUE_116 = 116
    VALUE_117 = 117
    VALUE_118 = 118
    VALUE_119 = 119
    VALUE_120 = 120
    VALUE_121 = 121
    VALUE_122 = 122
    VALUE_123 = 123
    VALUE_124 = 124
    VALUE_125 = 125
    VALUE_126 = 126
    VALUE_127 = 127
    VALUE_128 = 128
    VALUE_129 = 129
    VALUE_130 = 130
    VALUE_131 = 131
    VALUE_132 = 132
    VALUE_133 = 133
    VALUE_134 = 134
    VALUE_135 = 135
    VALUE_136 = 136
    VALUE_137 = 137
    VALUE_138 = 138
    VALUE_139 = 139
    VALUE_140 = 140


class TdDesUniMed(Enum):
    """
    Attributes:
        M: Metros
        CPM: Costo Por Mil
        UI: Unidad Internacional
        M3: Metros cúbicos
        UNI: Unidad
        G: Gramos
        LT: Litros
        MG: Miligramos
        CM: Centimetros
        CM2: Centimetros cuadrados
        CM3: Centimetros cubicos
        PUL: Pulgadas
        MM2: Milímetros cuadrados
        KG_M2: Kilogramos s/ metro cuadrado
        AA: Año
        ME: Mes
        TN: Tonelada
        HS: Hora
        MI: Minuto
        DET: Determinación
        YA: Yardas
        MT: Metros
        M2: Metros cuadrados
        MM: Milímetros
        SE: Segundo
        DI: Día
        KG: Kilogramos
        ML: Mililitros
        KM: Kilómetros
        ML_1: Metro lineal
        GL: Unidad Medida Global
        PM: Por Milaje
        HA: Hectáreas
        RACI_N: Ración
        VALUE_4_A: Bovinas
        CI: Curie
        DOC: Docena
        GLL: Galones (US) (3,7843 LT)
        GRO: Gruesas
        E4: Kilogramo Bruto
        KT: Kits
        M5: Microcurie
        MCU: Milicurie
        MIL: Millar
        PAR: Par
        FOT: Pies
        FTK: Pies Cuadradas
        PCE: Piezas
        KLT: Quilate
        RM: Resmas
        RO: Rollos
        K_WH: 1000 Kilowatt Hora
        U_JGO: Mazos
        DR: Tambores
        BX: Caja
        SET: Juego
        PK: Paquete
        BG: Bolsa
        DPC: Docena Par
        JR: Pote
        BL: Fardos
        AB: Bulto
        BK: Cesta
        BW: Peso Base
    """

    M = "m"
    CPM = "CPM"
    UI = "UI"
    M3 = "M3"
    UNI = "UNI"
    G = "g"
    LT = "LT"
    MG = "MG"
    CM = "CM"
    CM2 = "CM2"
    CM3 = "CM3"
    PUL = "PUL"
    MM2 = "MM2"
    KG_M2 = "kg/m2"
    AA = "AA"
    ME = "ME"
    TN = "TN"
    HS = "Hs"
    MI = "Mi"
    DET = "DET"
    YA = "Ya"
    MT = "MT"
    M2 = "M2"
    MM = "MM"
    SE = "Se"
    DI = "Di"
    KG = "kg"
    ML = "ML"
    KM = "Km"
    ML_1 = "ml"
    GL = "GL"
    PM = "pm"
    HA = "ha"
    RACI_N = "ración"
    VALUE_4_A = "4A"
    CI = "Ci"
    DOC = "DOC"
    GLL = "GLL"
    GRO = "GRO"
    E4 = "E4"
    KT = "KT"
    M5 = "M5"
    MCU = "MCU"
    MIL = "MIL"
    PAR = "PAR"
    FOT = "FOT"
    FTK = "FTK"
    PCE = "PCE"
    KLT = "KLT"
    RM = "RM"
    RO = "RO"
    K_WH = "kWh"
    U_JGO = "U(JGO)"
    DR = "DR"
    BX = "BX"
    SET = "SET"
    PK = "PK"
    BG = "BG"
    DPC = "DPC"
    JR = "JR"
    BL = "BL"
    AB = "AB"
    BK = "BK"
    BW = "BW"
