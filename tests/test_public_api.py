from kilasifen.engine import (
    ENDPOINTS,
    PRODUCCION,
    TEST,
    ConsultaSIFEN,
    TransmisionDE,
    TransmisionEvento,
    __all__,
    __version__,
    get_endpoint,
    sign_xml,
)


def test_public_api_exports_expected_symbols():
    assert __version__
    assert callable(sign_xml)
    assert PRODUCCION == 1
    assert TEST == 2
    assert isinstance(ENDPOINTS, dict)
    assert callable(get_endpoint)
    assert TransmisionDE.__name__ == "TransmisionDE"
    assert ConsultaSIFEN.__name__ == "ConsultaSIFEN"
    assert TransmisionEvento.__name__ == "TransmisionEvento"


def test_public_api_all_is_consistent():
    expected = {
        "__version__",
        "sign_xml",
        "PRODUCCION",
        "TEST",
        "ENDPOINTS",
        "get_endpoint",
        "TransmisionDE",
        "ConsultaSIFEN",
        "TransmisionEvento",
    }
    assert set(__all__) == expected
