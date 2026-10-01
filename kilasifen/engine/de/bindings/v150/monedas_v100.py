from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from kilasifen.engine.binding import BindingMixin

__NAMESPACE__ = "http://ekuatia.set.gov.py/sifen/xsd"


class CMondT(Enum):
    """
    Attributes:
        AED: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Dirham</ns1:CodeName>
        AFN: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Afghani</ns1:CodeName>
        ALL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Lek</ns1:CodeName>
        AMD: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Dram</ns1:CodeName>
        ANG: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Netherlands
            Antillian Guilder</ns1:CodeName>
        AOA: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kwanza</ns1:CodeName>
        ARS: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Argentine
            Peso</ns1:CodeName>
        AUD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Australian
            Dollar</ns1:CodeName>
        AWG: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Aruban
            Guilder</ns1:CodeName>
        AZM: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Azerbaijanian
            Manat</ns1:CodeName>
        BAM: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Convertible
            Mark</ns1:CodeName>
        BBD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Barbados
            Dollar</ns1:CodeName>
        BDT: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Taka</ns1:CodeName>
        BGN: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Bulgarian
            Lev</ns1:CodeName>
        BHD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Bahraini
            Dinar</ns1:CodeName>
        BIF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Burundi
            Franc</ns1:CodeName>
        BMD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Bermudian Dollar
            (customarily: Bermuda Dollar)</ns1:CodeName>
        BND: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Brunei
            Dollar</ns1:CodeName>
        BOB: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Boliviano</ns1:CodeName>
        BRL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Brazilian
            Real</ns1:CodeName>
        BSD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Bahamian
            Dollar</ns1:CodeName>
        BTN: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Ngultrum</ns1:CodeName>
        BWP: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Pula</ns1:CodeName>
        BYR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Belarussian
            Ruble</ns1:CodeName>
        BZD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Belize
            Dollar</ns1:CodeName>
        CAD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Canadian
            Dollar</ns1:CodeName>
        CDF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Franc
            Congolais</ns1:CodeName>
        CHF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Swiss
            Franc</ns1:CodeName>
        CLP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Chilean
            Peso</ns1:CodeName>
        CNY: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Yuan
            Renminbi</ns1:CodeName>
        COP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Colombian
            Peso</ns1:CodeName>
        CRC: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Costa Rican
            Colon</ns1:CodeName>
        CUP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Cuban
            Peso</ns1:CodeName>
        CVE: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Cape Verde
            Escudo</ns1:CodeName>
        CYP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Cyprus
            Pound</ns1:CodeName>
        CZK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Czech
            Koruna</ns1:CodeName>
        DJF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Djibouti
            Franc</ns1:CodeName>
        DKK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Danish
            Krone</ns1:CodeName>
        DOP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Dominican
            Peso</ns1:CodeName>
        DZD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Algerian
            Dinar</ns1:CodeName>
        EEK: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kroon</ns1:CodeName>
        EGP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Egyptian
            Pound</ns1:CodeName>
        ERN: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Nakfa</ns1:CodeName>
        ETB: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Ethopian
            Birr</ns1:CodeName>
        EUR: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Euro</ns1:CodeName>
        FJD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Fiji
            Dollar</ns1:CodeName>
        FKP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Falkland Islands
            Pound</ns1:CodeName>
        GBP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Pound
            Sterling</ns1:CodeName>
        GEL: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Lari</ns1:CodeName>
        GHC: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Cedi</ns1:CodeName>
        GIP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Gibraltar
            Pound</ns1:CodeName>
        GMD: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Dalasi</ns1:CodeName>
        GNF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Guinea
            Franc</ns1:CodeName>
        GTQ: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Quetzal</ns1:CodeName>
        GYD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Guyana
            Dollar</ns1:CodeName>
        HKD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Honk Kong
            Dollar</ns1:CodeName>
        HNL: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Lempira</ns1:CodeName>
        HRK: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kuna</ns1:CodeName>
        HTG: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Gourde</ns1:CodeName>
        HUF: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Forint</ns1:CodeName>
        IDR: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Rupiah</ns1:CodeName>
        ILS: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">New Israeli
            Sheqel</ns1:CodeName>
        INR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Indian
            Rupee</ns1:CodeName>
        IQD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Iraqi
            Dinar</ns1:CodeName>
        IRR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Iranian
            Rial</ns1:CodeName>
        ISK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Iceland
            Krona</ns1:CodeName>
        JMD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Jamaican
            Dollar</ns1:CodeName>
        JOD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Jordanian
            Dinar</ns1:CodeName>
        JPY: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Yen</ns1:CodeName>
        KES: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kenyan
            Shilling</ns1:CodeName>
        KGS: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Som</ns1:CodeName>
        KHR: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Riel</ns1:CodeName>
        KMF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Comoro
            Franc</ns1:CodeName>
        KPW: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">North Korean
            Won</ns1:CodeName>
        KRW: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Won</ns1:CodeName>
        KWD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kuwaiti
            Dinar</ns1:CodeName>
        KYD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Cayman Islands
            Dollar</ns1:CodeName>
        KZT: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Tenge</ns1:CodeName>
        LAK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kip</ns1:CodeName>
        LBP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Lebanese
            Pound</ns1:CodeName>
        LKR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Sri Lanka
            Rupee</ns1:CodeName>
        LRD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Liberian
            Dollar</ns1:CodeName>
        LSL: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Loti</ns1:CodeName>
        LTL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Lithuanian
            Litas</ns1:CodeName>
        LVL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Latvian
            Lats</ns1:CodeName>
        LYD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Libyan
            Dinar</ns1:CodeName>
        MAD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Morrocan
            Dirham</ns1:CodeName>
        MDL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Moldovan
            Leu</ns1:CodeName>
        MGF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Malagasy
            Franc</ns1:CodeName>
        MKD: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Denar</ns1:CodeName>
        MMK: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kyat</ns1:CodeName>
        MNT: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Tugrik</ns1:CodeName>
        MOP: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Pataca</ns1:CodeName>
        MRO: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Ouguiya</ns1:CodeName>
        MTL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Maltese
            Lira</ns1:CodeName>
        MUR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Mauritius
            Rupee</ns1:CodeName>
        MVR: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Rufiyaa</ns1:CodeName>
        MWK: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kwacha</ns1:CodeName>
        MXN: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Mexican
            Peso</ns1:CodeName>
        MYR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Malaysian
            Ringgit</ns1:CodeName>
        MZM: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Metical</ns1:CodeName>
        NAD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Namibia
            Dollar</ns1:CodeName>
        NGN: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Naira</ns1:CodeName>
        NIO: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Cordoba
            Oro</ns1:CodeName>
        NOK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Norwegian
            Krone</ns1:CodeName>
        NPR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Nepalese
            Rupee</ns1:CodeName>
        NZD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">New Zealand
            Dollar</ns1:CodeName>
        OMR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Rial
            Omani</ns1:CodeName>
        PAB: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Balboa</ns1:CodeName>
        PEN: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Nuevo
            Sol</ns1:CodeName>
        PGK: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kina</ns1:CodeName>
        PHP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Philippine
            Peso</ns1:CodeName>
        PKR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Pakistan
            Rupee</ns1:CodeName>
        PLN: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Zloty</ns1:CodeName>
        PYG: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Guarani</ns1:CodeName>
        QAR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Qatari
            Rial</ns1:CodeName>
        ROL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Leu</ns1:CodeName>
        RUB: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Russian
            Ruble</ns1:CodeName>
        RWF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Rwanda
            Franc</ns1:CodeName>
        SAR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Saudi
            Riyal</ns1:CodeName>
        SBD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Solomon Islands
            Dollar</ns1:CodeName>
        SCR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Seychelles
            Rupee</ns1:CodeName>
        SDD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Sudanese
            Dinar</ns1:CodeName>
        SEK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Swedish
            Krona</ns1:CodeName>
        SGD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Singapore
            Dollar</ns1:CodeName>
        SHP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">St. Helena
            Pound</ns1:CodeName>
        SIT: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Tolar</ns1:CodeName>
        SKK: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Slovak
            Koruna</ns1:CodeName>
        SLL: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Leone</ns1:CodeName>
        SOS: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Somali
            Shilling</ns1:CodeName>
        SRG: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Suriname
            Guilder</ns1:CodeName>
        STD: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Dobra</ns1:CodeName>
        SVC: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">El Salvador
            Colon</ns1:CodeName>
        SYP: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Syrian
            Pound</ns1:CodeName>
        SZL: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Lilangeni</ns1:CodeName>
        THB: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Baht</ns1:CodeName>
        TJS: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Somoni</ns1:CodeName>
        TMM: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Manat</ns1:CodeName>
        TND: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Tunisian
            Dinar</ns1:CodeName>
        TOP: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Pa'anga</ns1:CodeName>
        TRL: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Turkish
            Lira</ns1:CodeName>
        TTD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Trinidad and
            Tobago Dollar</ns1:CodeName>
        TWD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">New Taiwan
            Dollar</ns1:CodeName>
        TZS: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Tanzanian
            Shilling</ns1:CodeName>
        UAH: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Hryvnia</ns1:CodeName>
        UGX: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Uganda
            Shilling</ns1:CodeName>
        USD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">US
            Dollar</ns1:CodeName>
        UYU: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Peso
            Uruguayo</ns1:CodeName>
        UZS: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Uzbekistan
            Sum</ns1:CodeName>
        VEB: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Bolivar</ns1:CodeName>
        VND: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Dong</ns1:CodeName>
        VUV: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Vatu</ns1:CodeName>
        WST: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Tala</ns1:CodeName>
        XAF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">CFA
            Franc</ns1:CodeName>
        XAG: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Silver</ns1:CodeName>
        XAU: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Gold</ns1:CodeName>
        XCD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">East Carribean
            Dollar</ns1:CodeName>
        XDR: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">SDR</ns1:CodeName>
        XOF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">CFA
            Franc</ns1:CodeName>
        XPD: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Palladium</ns1:CodeName>
        XPF: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">CFP
            Franc</ns1:CodeName>
        XPT: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Platinum</ns1:CodeName>
        YER: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Yemeni
            Rial</ns1:CodeName>
        YUM: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">New
            Dinar</ns1:CodeName>
        ZAR: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Rand</ns1:CodeName>
        ZMK: <ns1:CodeName
            xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Kwacha</ns1:CodeName>
        ZWD: <ns1:CodeName xmlns:ns1="http://ekuatia.set.gov.py/sifen/xsd">Zimbabwe
            Dollar</ns1:CodeName>
    """

    AED = "AED"
    AFN = "AFN"
    ALL = "ALL"
    AMD = "AMD"
    ANG = "ANG"
    AOA = "AOA"
    ARS = "ARS"
    AUD = "AUD"
    AWG = "AWG"
    AZM = "AZM"
    BAM = "BAM"
    BBD = "BBD"
    BDT = "BDT"
    BGN = "BGN"
    BHD = "BHD"
    BIF = "BIF"
    BMD = "BMD"
    BND = "BND"
    BOB = "BOB"
    BRL = "BRL"
    BSD = "BSD"
    BTN = "BTN"
    BWP = "BWP"
    BYR = "BYR"
    BZD = "BZD"
    CAD = "CAD"
    CDF = "CDF"
    CHF = "CHF"
    CLP = "CLP"
    CNY = "CNY"
    COP = "COP"
    CRC = "CRC"
    CUP = "CUP"
    CVE = "CVE"
    CYP = "CYP"
    CZK = "CZK"
    DJF = "DJF"
    DKK = "DKK"
    DOP = "DOP"
    DZD = "DZD"
    EEK = "EEK"
    EGP = "EGP"
    ERN = "ERN"
    ETB = "ETB"
    EUR = "EUR"
    FJD = "FJD"
    FKP = "FKP"
    GBP = "GBP"
    GEL = "GEL"
    GHC = "GHC"
    GIP = "GIP"
    GMD = "GMD"
    GNF = "GNF"
    GTQ = "GTQ"
    GYD = "GYD"
    HKD = "HKD"
    HNL = "HNL"
    HRK = "HRK"
    HTG = "HTG"
    HUF = "HUF"
    IDR = "IDR"
    ILS = "ILS"
    INR = "INR"
    IQD = "IQD"
    IRR = "IRR"
    ISK = "ISK"
    JMD = "JMD"
    JOD = "JOD"
    JPY = "JPY"
    KES = "KES"
    KGS = "KGS"
    KHR = "KHR"
    KMF = "KMF"
    KPW = "KPW"
    KRW = "KRW"
    KWD = "KWD"
    KYD = "KYD"
    KZT = "KZT"
    LAK = "LAK"
    LBP = "LBP"
    LKR = "LKR"
    LRD = "LRD"
    LSL = "LSL"
    LTL = "LTL"
    LVL = "LVL"
    LYD = "LYD"
    MAD = "MAD"
    MDL = "MDL"
    MGF = "MGF"
    MKD = "MKD"
    MMK = "MMK"
    MNT = "MNT"
    MOP = "MOP"
    MRO = "MRO"
    MTL = "MTL"
    MUR = "MUR"
    MVR = "MVR"
    MWK = "MWK"
    MXN = "MXN"
    MYR = "MYR"
    MZM = "MZM"
    NAD = "NAD"
    NGN = "NGN"
    NIO = "NIO"
    NOK = "NOK"
    NPR = "NPR"
    NZD = "NZD"
    OMR = "OMR"
    PAB = "PAB"
    PEN = "PEN"
    PGK = "PGK"
    PHP = "PHP"
    PKR = "PKR"
    PLN = "PLN"
    PYG = "PYG"
    QAR = "QAR"
    ROL = "ROL"
    RUB = "RUB"
    RWF = "RWF"
    SAR = "SAR"
    SBD = "SBD"
    SCR = "SCR"
    SDD = "SDD"
    SEK = "SEK"
    SGD = "SGD"
    SHP = "SHP"
    SIT = "SIT"
    SKK = "SKK"
    SLL = "SLL"
    SOS = "SOS"
    SRG = "SRG"
    STD = "STD"
    SVC = "SVC"
    SYP = "SYP"
    SZL = "SZL"
    THB = "THB"
    TJS = "TJS"
    TMM = "TMM"
    TND = "TND"
    TOP = "TOP"
    TRL = "TRL"
    TTD = "TTD"
    TWD = "TWD"
    TZS = "TZS"
    UAH = "UAH"
    UGX = "UGX"
    USD = "USD"
    UYU = "UYU"
    UZS = "UZS"
    VEB = "VEB"
    VND = "VND"
    VUV = "VUV"
    WST = "WST"
    XAF = "XAF"
    XAG = "XAG"
    XAU = "XAU"
    XCD = "XCD"
    XDR = "XDR"
    XOF = "XOF"
    XPD = "XPD"
    XPF = "XPF"
    XPT = "XPT"
    YER = "YER"
    YUM = "YUM"
    ZAR = "ZAR"
    ZMK = "ZMK"
    ZWD = "ZWD"


@dataclass(kw_only=True)
class CurrencyCodeType(BindingMixin):
    """
    ISO 4217 Alpha.
    """

    value: CMondT = field()
    codeListID: str = field(
        init=False,
        default="ISO 4217 Alpha",
        metadata={
            "type": "Attribute",
        },
    )
