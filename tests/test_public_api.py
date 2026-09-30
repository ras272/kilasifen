from kilasifen.engine import (
    ENDPOINTS,
    PRODUCCION,
    TEST,
    ConsultaSIFEN,
    TransmissaoDE,
    TransmissaoEvento,
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
    assert TransmissaoDE.__name__ == "TransmissaoDE"
    assert ConsultaSIFEN.__name__ == "ConsultaSIFEN"
    assert TransmissaoEvento.__name__ == "TransmissaoEvento"


def test_public_api_all_is_consistent():
    expected = {
        "__version__",
        "sign_xml",
        "PRODUCCION",
        "TEST",
        "ENDPOINTS",
        "get_endpoint",
        "TransmissaoDE",
        "ConsultaSIFEN",
        "TransmissaoEvento",
    }
    assert set(__all__) == expected
