from __future__ import annotations

from enum import Enum

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


class PaisType(Enum):
    """
    Attributes:
        MKD: Macedonia del Norte
        TWN: Taiwán (Provincia de China)
        DZA: Argelia
        EGY: Egipto
        LBY: Libia
        MAR: Marruecos
        SDN: Sudán
        TUN: Túnez
        ESH: Sáhara Occidental
        IOT: Territorio Británico del Océano Índico
        BDI: Burundi
        COM: Comoras
        DJI: Djibouti
        ERI: Eritrea
        ETH: Etiopía
        ATF: Territorio de las Tierras Australes Francesas
        KEN: Kenya
        MDG: Madagascar
        MWI: Malawi
        MUS: Mauricio
        MYT: Mayotte
        MOZ: Mozambique
        REU: Reunión
        RWA: Rwanda
        SYC: Seychelles
        SOM: Somalia
        SSD: Sudán del Sur
        UGA: Uganda
        TZA: República Unida de Tanzanía
        ZMB: Zambia
        ZWE: Zimbabwe
        AGO: Angola
        CMR: Camerún
        CAF: República Centroafricana
        TCD: Chad
        COG: Congo
        COD: República Democrática del Congo
        GNQ: Guinea Ecuatorial
        GAB: Gabón
        STP: Santo Tomé y Príncipe
        BWA: Botswana
        LSO: Lesotho
        NAM: Namibia
        ZAF: Sudáfrica
        SWZ: Swazilandia
        BEN: Benin
        BFA: Burkina Faso
        CPV: Cabo Verde
        CIV: Côte d'Ivoire
        GMB: Gambia
        GHA: Ghana
        GIN: Guinea
        GNB: Guinea-Bissau
        LBR: Liberia
        MLI: Malí
        MRT: Mauritania
        NER: Níger
        NGA: Nigeria
        SHN: Santa Elena
        SEN: Senegal
        SLE: Sierra Leona
        TGO: Togo
        AIA: Anguila
        ATG: Antigua y Barbuda
        ABW: Aruba
        BHS: Bahamas
        BRB: Barbados
        BES: Bonaire, San Eustaquio y Saba
        VGB: Islas Vírgenes Británicas
        CYM: Islas Caimán
        CUB: CUBA
        CUW: Curaçao
        DMA: Dominica
        DOM: República Dominicana
        GRD: Granada
        GLP: Guadalupe
        HTI: Haití
        JAM: Jamaica
        MTQ: Martinica
        MSR: Montserrat
        PRI: Puerto Rico
        BLM: San Bartolomé
        KNA: Saint Kitts y Nevis
        LCA: Santa Lucía
        MAF: San Martín (parte francesa)
        VCT: San Vicente y las Granadinas
        SXM: San Martín (parte holandés)
        TTO: Trinidad y Tabago
        TCA: Islas Turcas y Caicos
        VIR: Islas Vírgenes de los Estados Unidos
        BLZ: Belice
        CRI: Costa Rica
        SLV: El Salvador
        GTM: Guatemala
        HND: Honduras
        MEX: México
        NIC: Nicaragua
        PAN: Panamá
        ARG: Argentina
        BOL: Bolivia (Estado Plurinacional de)
        BRA: Brasil
        CHL: Chile
        COL: Colombia
        ECU: Ecuador
        FLK: Islas Malvinas (Falkland)
        GUF: Guayana Francesa
        GUY: Guyana
        PRY: Paraguay
        PER: Perú
        SGS: Georgia del Sur y las Islas Sandwich del Sur
        SUR: Suriname
        URY: Uruguay
        VEN: Venezuela (República Bolivariana de)
        BMU: Bermuda
        CAN: Canadá
        GRL: Groenlandia
        SPM: Saint Pierre y Miquelon
        USA: Estados Unidos de América
        ATA: Antártida
        KAZ: Kazajstán
        KGZ: Kirguistán
        TJK: Tayikistán
        TKM: Turkmenistán
        UZB: Uzbekistán
        CHN: China
        HKG: Hong Kong
        MAC: Macao
        PRK: República Popular Democrática de Corea
        JPN: Japón
        MNG: Mongolia
        KOR: República de Corea
        BRN: Brunei Darussalam
        KHM: Camboya
        IDN: Indonesia
        LAO: República Democrática Popular Lao
        MYS: Malasia
        MMR: Myanmar
        PHL: Filipinas
        SGP: Singapur
        THA: Tailandia
        TLS: Timor-Leste
        VNM: Viet Nam
        AFG: Afganistán
        BGD: Bangladesh
        BTN: Bhután
        IND: India
        IRN: Irán (República Islámica del)
        MDV: Maldivas
        NPL: Nepal
        PAK: Pakistán
        LKA: Sri Lanka
        ARM: Armenia
        AZE: Azerbaiyán
        BHR: Bahrein
        CYP: Chipre
        GEO: Georgia
        IRQ: Iraq
        ISR: Israel
        JOR: Jordania
        KWT: Kuwait
        LBN: Líbano
        OMN: Omán
        QAT: Qatar
        SAU: Arabia Saudita
        PSE: Estado de Palestina
        SYR: República Árabe Siria
        TUR: Turquía
        ARE: Emiratos Árabes Unidos
        YEM: Yemen
        BLR: Belarús
        BGR: Bulgaria
        CZE: Chequia
        HUN: Hungría
        POL: Polonia
        MDA: República de Moldova
        ROU: Rumania
        RUS: Federación de Rusia
        SVK: Eslovaquia
        UKR: Ucrania
        ALA: Islas Åland
        GGY: Guernsey
        JEY: Jersey
        DNK: Dinamarca
        EST: Estonia
        FRO: Islas Feroe
        FIN: Finlandia
        ISL: Islandia
        IRL: Irlanda
        IMN: Isla de Man
        LVA: Letonia
        LTU: Lituania
        NOR: Noruega
        SJM: Islas Svalbard y Jan Mayen
        SWE: Suecia
        GBR: Reino Unido de Gran Bretaña e Irlanda del Norte
        ALB: Albania
        AND: Andorra
        BIH: Bosnia y Herzegovina
        HRV: Croacia
        GIB: Gibraltar
        GRC: Grecia
        VAT: Santa Sede
        ITA: Italia
        MLT: Malta
        MNE: Montenegro
        PRT: Portugal
        SMR: San Marino
        SRB: Serbia
        SVN: Eslovenia
        ESP: España
        AUT: Austria
        BEL: Bélgica
        FRA: Francia
        DEU: Alemania
        LIE: Liechtenstein
        LUX: Luxemburgo
        MCO: Mónaco
        NLD: Países Bajos
        CHE: Suiza
        AUS: Australia
        CXR: Isla de Navidad
        CCK: Islas Cocos (Keeling)
        HMD: Islas Heard y McDonald
        NZL: Nueva Zelandia
        NFK: Islas Norfolk
        FJI: Fiji
        NCL: Nueva Caledonia
        PNG: Papua Nueva Guinea
        SLB: Islas Salomón
        VUT: Vanuatu
        GUM: Guam
        KIR: Kiribati
        MHL: Islas Marshall
        FSM: Micronesia (Estados Federados de)
        NRU: Nauru
        MNP: Islas Marianas Septentrionales
        PLW: Palau
        UMI: Islas menores alejadas de Estados Unidos
        ASM: Samoa Americana
        COK: Islas Cook
        PYF: Polinesia Francesa
        NIU: Niue
        PCN: Pitcairn
        WSM: Samoa
        TKL: Tokelau
        TON: Tonga
        TUV: Tuvalu
        WLF: Islas Wallis y Futuna
        NN: NO EXISTE
    """

    MKD = "MKD"
    TWN = "TWN"
    DZA = "DZA"
    EGY = "EGY"
    LBY = "LBY"
    MAR = "MAR"
    SDN = "SDN"
    TUN = "TUN"
    ESH = "ESH"
    IOT = "IOT"
    BDI = "BDI"
    COM = "COM"
    DJI = "DJI"
    ERI = "ERI"
    ETH = "ETH"
    ATF = "ATF"
    KEN = "KEN"
    MDG = "MDG"
    MWI = "MWI"
    MUS = "MUS"
    MYT = "MYT"
    MOZ = "MOZ"
    REU = "REU"
    RWA = "RWA"
    SYC = "SYC"
    SOM = "SOM"
    SSD = "SSD"
    UGA = "UGA"
    TZA = "TZA"
    ZMB = "ZMB"
    ZWE = "ZWE"
    AGO = "AGO"
    CMR = "CMR"
    CAF = "CAF"
    TCD = "TCD"
    COG = "COG"
    COD = "COD"
    GNQ = "GNQ"
    GAB = "GAB"
    STP = "STP"
    BWA = "BWA"
    LSO = "LSO"
    NAM = "NAM"
    ZAF = "ZAF"
    SWZ = "SWZ"
    BEN = "BEN"
    BFA = "BFA"
    CPV = "CPV"
    CIV = "CIV"
    GMB = "GMB"
    GHA = "GHA"
    GIN = "GIN"
    GNB = "GNB"
    LBR = "LBR"
    MLI = "MLI"
    MRT = "MRT"
    NER = "NER"
    NGA = "NGA"
    SHN = "SHN"
    SEN = "SEN"
    SLE = "SLE"
    TGO = "TGO"
    AIA = "AIA"
    ATG = "ATG"
    ABW = "ABW"
    BHS = "BHS"
    BRB = "BRB"
    BES = "BES"
    VGB = "VGB"
    CYM = "CYM"
    CUB = "CUB"
    CUW = "CUW"
    DMA = "DMA"
    DOM = "DOM"
    GRD = "GRD"
    GLP = "GLP"
    HTI = "HTI"
    JAM = "JAM"
    MTQ = "MTQ"
    MSR = "MSR"
    PRI = "PRI"
    BLM = "BLM"
    KNA = "KNA"
    LCA = "LCA"
    MAF = "MAF"
    VCT = "VCT"
    SXM = "SXM"
    TTO = "TTO"
    TCA = "TCA"
    VIR = "VIR"
    BLZ = "BLZ"
    CRI = "CRI"
    SLV = "SLV"
    GTM = "GTM"
    HND = "HND"
    MEX = "MEX"
    NIC = "NIC"
    PAN = "PAN"
    ARG = "ARG"
    BOL = "BOL"
    BRA = "BRA"
    CHL = "CHL"
    COL = "COL"
    ECU = "ECU"
    FLK = "FLK"
    GUF = "GUF"
    GUY = "GUY"
    PRY = "PRY"
    PER = "PER"
    SGS = "SGS"
    SUR = "SUR"
    URY = "URY"
    VEN = "VEN"
    BMU = "BMU"
    CAN = "CAN"
    GRL = "GRL"
    SPM = "SPM"
    USA = "USA"
    ATA = "ATA"
    KAZ = "KAZ"
    KGZ = "KGZ"
    TJK = "TJK"
    TKM = "TKM"
    UZB = "UZB"
    CHN = "CHN"
    HKG = "HKG"
    MAC = "MAC"
    PRK = "PRK"
    JPN = "JPN"
    MNG = "MNG"
    KOR = "KOR"
    BRN = "BRN"
    KHM = "KHM"
    IDN = "IDN"
    LAO = "LAO"
    MYS = "MYS"
    MMR = "MMR"
    PHL = "PHL"
    SGP = "SGP"
    THA = "THA"
    TLS = "TLS"
    VNM = "VNM"
    AFG = "AFG"
    BGD = "BGD"
    BTN = "BTN"
    IND = "IND"
    IRN = "IRN"
    MDV = "MDV"
    NPL = "NPL"
    PAK = "PAK"
    LKA = "LKA"
    ARM = "ARM"
    AZE = "AZE"
    BHR = "BHR"
    CYP = "CYP"
    GEO = "GEO"
    IRQ = "IRQ"
    ISR = "ISR"
    JOR = "JOR"
    KWT = "KWT"
    LBN = "LBN"
    OMN = "OMN"
    QAT = "QAT"
    SAU = "SAU"
    PSE = "PSE"
    SYR = "SYR"
    TUR = "TUR"
    ARE = "ARE"
    YEM = "YEM"
    BLR = "BLR"
    BGR = "BGR"
    CZE = "CZE"
    HUN = "HUN"
    POL = "POL"
    MDA = "MDA"
    ROU = "ROU"
    RUS = "RUS"
    SVK = "SVK"
    UKR = "UKR"
    ALA = "ALA"
    GGY = "GGY"
    JEY = "JEY"
    DNK = "DNK"
    EST = "EST"
    FRO = "FRO"
    FIN = "FIN"
    ISL = "ISL"
    IRL = "IRL"
    IMN = "IMN"
    LVA = "LVA"
    LTU = "LTU"
    NOR = "NOR"
    SJM = "SJM"
    SWE = "SWE"
    GBR = "GBR"
    ALB = "ALB"
    AND = "AND"
    BIH = "BIH"
    HRV = "HRV"
    GIB = "GIB"
    GRC = "GRC"
    VAT = "VAT"
    ITA = "ITA"
    MLT = "MLT"
    MNE = "MNE"
    PRT = "PRT"
    SMR = "SMR"
    SRB = "SRB"
    SVN = "SVN"
    ESP = "ESP"
    AUT = "AUT"
    BEL = "BEL"
    FRA = "FRA"
    DEU = "DEU"
    LIE = "LIE"
    LUX = "LUX"
    MCO = "MCO"
    NLD = "NLD"
    CHE = "CHE"
    AUS = "AUS"
    CXR = "CXR"
    CCK = "CCK"
    HMD = "HMD"
    NZL = "NZL"
    NFK = "NFK"
    FJI = "FJI"
    NCL = "NCL"
    PNG = "PNG"
    SLB = "SLB"
    VUT = "VUT"
    GUM = "GUM"
    KIR = "KIR"
    MHL = "MHL"
    FSM = "FSM"
    NRU = "NRU"
    MNP = "MNP"
    PLW = "PLW"
    UMI = "UMI"
    ASM = "ASM"
    COK = "COK"
    PYF = "PYF"
    NIU = "NIU"
    PCN = "PCN"
    WSM = "WSM"
    TKL = "TKL"
    TON = "TON"
    TUV = "TUV"
    WLF = "WLF"
    NN = "NN"
