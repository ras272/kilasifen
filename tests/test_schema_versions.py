"""Integridad de los XSD y bindings locales, y deteccion de XSD nuevos en la SET.

- ``TestIntegridadEsquemas``: los XSD oficiales estan en
  ``kilasifen/engine/de/schemas/v150``, son UTF-8 y no apuntan a ubicaciones
  remotas.
- ``TestIntegridadBindings``: cada modulo generado por xsdata se importa.
- ``TestComparacionListadoSet``: la logica que compara el listado publicado por
  la SET con los XSD locales, y que toda falla de la descarga llegue al test
  como error, probadas sin red.
- ``TestSchemaUpdates``: descarga el listado de la SET y falla si publica un
  XSD que no esta en el repositorio. Solo corre con la variable de entorno
  ``CHECK_SCHEMA_UPDATES`` activada (el CI la define en un job semanal que
  selecciona esta clase por nombre). Una vez activada nunca se omite: cualquier
  error de conexion (DNS incluido), HTTP, TLS, timeout o de decodificacion
  deja el test en rojo, porque ese job es la alarma.

Al importar o coleccionar el modulo solo se usa la libreria estandar y
pytest: el job semanal no instala los extras del motor, y una rotura de los
bindings tiene que verse como fallo de su test, no como error de coleccion
que impida correr ``TestSchemaUpdates``.
"""

from __future__ import annotations

import email.message
import importlib
import os
import pkgutil
import re
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import pytest

RAIZ_REPO = Path(__file__).resolve().parents[1]
DIR_ESQUEMAS = RAIZ_REPO / "kilasifen" / "engine" / "de" / "schemas" / "v150"
DIR_BINDINGS = RAIZ_REPO / "kilasifen" / "engine" / "de" / "bindings" / "v150"
PAQUETE_BINDINGS = "kilasifen.engine.de.bindings.v150"

ESQUEMAS_PRINCIPALES = (
    "DE_v150.xsd",
    "DE_Types_v150.xsd",
    "Evento_v150.xsd",
    "Paises_v100.xsd",
    "Unidades_Medida_v141.xsd",
    "xmldsig-core-schema.xsd",
)
ESQUEMAS_WS = (
    "siRecepDE_v150.xsd",
    "siRecepRDE_v150.xsd",
    "siRecepEvento_v150.xsd",
    "protProcesDE_v150.xsd",
)
MINIMO_ESQUEMAS = 40
MINIMO_MODULOS_BINDINGS = 20

#: Comienzo de una ubicacion remota de XSD. El namespace del SIFEN es la misma
#: URL sin la barra final y si esta permitido.
UBICACION_REMOTA = "ekuatia.set.gov.py/sifen/xsd/"

URL_LISTADO_SET = "https://ekuatia.set.gov.py/sifen/xsd/"
AGENTE_HTTP = "Mozilla/5.0"
TIEMPO_ESPERA_S = 30
VARIABLE_ACTIVACION = "CHECK_SCHEMA_UPDATES"
_VALORES_APAGADO = frozenset({"", "0", "false", "no", "off"})

#: Enlaces ``href="..."`` cuyo valor termina en ``.xsd``.
_ENLACE_XSD = re.compile(r'href="([^"]*\.xsd)"')


# ---------------------------------------------------------------------------
# Auxiliares (solo libreria estandar)
# ---------------------------------------------------------------------------


def _rutas_esquemas() -> list[Path]:
    """Archivos ``.xsd`` de ``DIR_ESQUEMAS`` (sin recursion), ordenados."""
    if not DIR_ESQUEMAS.is_dir():
        return []
    return sorted(
        ruta
        for ruta in DIR_ESQUEMAS.iterdir()
        if ruta.is_file() and ruta.name.endswith(".xsd")
    )


def _esquemas_locales() -> set[str]:
    """Nombres de los XSD versionados en el repositorio."""
    return {ruta.name for ruta in _rutas_esquemas()}


def _modulos_en_directorio() -> list[str]:
    """Modulos de primer nivel del paquete de bindings, sin importarlo."""
    if not DIR_BINDINGS.is_dir():
        return []
    return sorted(info.name for info in pkgutil.iter_modules([str(DIR_BINDINGS)]))


def _deteccion_activada(valor: str | None) -> bool:
    """Indica si el valor de ``CHECK_SCHEMA_UPDATES`` pide consultar la SET."""
    return (valor or "").strip().lower() not in _VALORES_APAGADO


def _esquemas_publicados(html: str) -> set[str]:
    """Nombres de archivo de los XSD enlazados en el listado HTML de la SET."""
    return {valor.rsplit("/", 1)[-1] for valor in _ENLACE_XSD.findall(html)}


def _esquemas_nuevos(
    publicados: Iterable[str], locales: Iterable[str]
) -> list[str]:
    """XSD publicados que faltan en el repositorio, en orden alfabetico."""
    return sorted(set(publicados) - set(locales))


def _mensaje_esquemas_nuevos(nuevos: Sequence[str]) -> str:
    """Mensaje de fallo que nombra los XSD nuevos."""
    destino = DIR_ESQUEMAS.relative_to(RAIZ_REPO).as_posix()
    return (
        f"La SET publico {len(nuevos)} XSD que no estan en {destino}: "
        f"{', '.join(nuevos)}. Hay que descargarlos y regenerar los bindings."
    )


def _descargar_listado_set() -> str:
    """Descarga el listado HTML de XSD que publica la SET.

    La verificacion TLS queda activa (cadena de certificados y nombre de
    host) y las redirecciones se siguen. El cuerpo se decodifica en modo
    estricto con el charset que declara la respuesta, o UTF-8 si no declara
    ninguno.
    """
    pedido = urllib.request.Request(
        URL_LISTADO_SET, headers={"User-Agent": AGENTE_HTTP}
    )
    contexto = ssl.create_default_context()
    with urllib.request.urlopen(
        pedido, timeout=TIEMPO_ESPERA_S, context=contexto
    ) as respuesta:
        charset = respuesta.headers.get_content_charset() or "utf-8"
        return respuesta.read().decode(charset)


def _verificar_listado_set() -> None:
    """Falla si la SET publica un XSD que no esta en el repositorio.

    No captura ningun error de la descarga: conexion, DNS, HTTP, TLS,
    timeout y decodificacion se propagan tal cual y dejan el test en rojo.
    Convertirlos en omision apagaria la alarma del job semanal.
    """
    publicados = _esquemas_publicados(_descargar_listado_set())
    assert publicados, (
        f"el listado de {URL_LISTADO_SET} no enlaza ningun .xsd; "
        "revisar si cambio su formato"
    )
    nuevos = _esquemas_nuevos(publicados, _esquemas_locales())
    if nuevos:
        pytest.fail(_mensaje_esquemas_nuevos(nuevos))


# ---------------------------------------------------------------------------
# Esquemas XSD locales
# ---------------------------------------------------------------------------


class TestIntegridadEsquemas:
    """Los XSD oficiales de v150 estan completos y se resuelven localmente."""

    def test_existe_directorio_esquemas(self) -> None:
        assert DIR_ESQUEMAS.is_dir(), f"no existe el directorio {DIR_ESQUEMAS}"

    @pytest.mark.parametrize("nombre", ESQUEMAS_PRINCIPALES)
    def test_esquemas_principales_presentes(self, nombre: str) -> None:
        assert (DIR_ESQUEMAS / nombre).is_file(), f"falta el XSD {nombre}"

    @pytest.mark.parametrize("nombre", ESQUEMAS_WS)
    def test_esquemas_ws_presentes(self, nombre: str) -> None:
        assert (DIR_ESQUEMAS / nombre).is_file(), f"falta el XSD {nombre}"

    def test_sin_referencias_remotas(self) -> None:
        no_utf8: list[str] = []
        remotos: list[str] = []
        for ruta in _rutas_esquemas():
            try:
                texto = ruta.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                no_utf8.append(ruta.name)
                continue
            if UBICACION_REMOTA in texto:
                remotos.append(ruta.name)
        assert not no_utf8, f"XSD que no son UTF-8 valido: {', '.join(no_utf8)}"
        assert not remotos, (
            f"XSD con ubicaciones remotas ({UBICACION_REMOTA}): "
            f"{', '.join(remotos)}"
        )

    def test_cantidad_minima_esquemas(self) -> None:
        cantidad = len(_rutas_esquemas())
        assert cantidad >= MINIMO_ESQUEMAS, (
            f"hay {cantidad} XSD en {DIR_ESQUEMAS}; "
            f"se esperaban al menos {MINIMO_ESQUEMAS}"
        )


# ---------------------------------------------------------------------------
# Bindings generados
# ---------------------------------------------------------------------------


class TestIntegridadBindings:
    """Los modulos generados por xsdata se importan sin errores."""

    def test_fe_v141_expone_rde(self) -> None:
        modulo = importlib.import_module(f"{PAQUETE_BINDINGS}.fe_v141")
        assert hasattr(modulo, "RDe")

    @pytest.mark.parametrize("modulo", _modulos_en_directorio())
    def test_modulos_bindings_importables(self, modulo: str) -> None:
        importlib.import_module(f"{PAQUETE_BINDINGS}.{modulo}")

    def test_cantidad_minima_modulos(self) -> None:
        paquete = importlib.import_module(PAQUETE_BINDINGS)
        modulos = sorted(info.name for info in pkgutil.iter_modules(paquete.__path__))
        assert len(modulos) >= MINIMO_MODULOS_BINDINGS, (
            f"hay {len(modulos)} modulos de bindings; "
            f"se esperaban al menos {MINIMO_MODULOS_BINDINGS}"
        )
        # La parametrizacion de ``test_modulos_bindings_importables`` lista el
        # directorio sin importar el paquete: tiene que ver los mismos modulos.
        assert modulos == _modulos_en_directorio()


# ---------------------------------------------------------------------------
# Comparacion con el listado de la SET (sin red)
# ---------------------------------------------------------------------------


def _listado_html(*enlaces: str) -> str:
    """Listado de directorio minimo, con la forma del que publica la SET."""
    filas = "\n".join(f'<li><a href="{enlace}">{enlace}</a></li>' for enlace in enlaces)
    return f"<html><body><ul>\n{filas}\n</ul></body></html>"


class _RespuestaFalsa:
    """Respuesta HTTP en memoria para ``urllib.request.urlopen``."""

    def __init__(self, cuerpo: bytes, tipo_contenido: str) -> None:
        self.headers = email.message.Message()
        self.headers["Content-Type"] = tipo_contenido
        self._cuerpo = cuerpo
        self.cerrada = False

    def __enter__(self) -> _RespuestaFalsa:
        return self

    def __exit__(self, *_: object) -> None:
        self.cerrada = True

    def read(self) -> bytes:
        return self._cuerpo


def _urlopen_que_lanza(error: BaseException) -> Callable[..., _RespuestaFalsa]:
    """``urlopen`` sustituto que falla con ``error`` sin tocar la red."""

    def urlopen_falso(*_args: object, **_kwargs: object) -> _RespuestaFalsa:
        raise error

    return urlopen_falso


def _urlopen_que_responde(
    cuerpo: bytes, tipo_contenido: str
) -> Callable[..., _RespuestaFalsa]:
    """``urlopen`` sustituto que devuelve siempre el mismo cuerpo."""

    def urlopen_falso(*_args: object, **_kwargs: object) -> _RespuestaFalsa:
        return _RespuestaFalsa(cuerpo, tipo_contenido)

    return urlopen_falso


#: Fallas de la descarga y la excepcion que debe llegar al test de la SET.
_FALLAS_DE_DESCARGA = [
    pytest.param(
        _urlopen_que_lanza(
            urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        ),
        urllib.error.URLError,
        id="dns",
    ),
    pytest.param(
        _urlopen_que_lanza(
            urllib.error.URLError(OSError("Network is unreachable"))
        ),
        urllib.error.URLError,
        id="sin_ruta",
    ),
    pytest.param(
        _urlopen_que_lanza(
            urllib.error.URLError(ConnectionRefusedError("conexion rechazada"))
        ),
        urllib.error.URLError,
        id="rechazada",
    ),
    pytest.param(
        _urlopen_que_lanza(
            urllib.error.HTTPError(URL_LISTADO_SET, 503, "No disponible", {}, None)
        ),
        urllib.error.HTTPError,
        id="http_503",
    ),
    pytest.param(
        _urlopen_que_lanza(
            urllib.error.URLError(ssl.SSLCertVerificationError("cadena"))
        ),
        urllib.error.URLError,
        id="tls",
    ),
    pytest.param(
        _urlopen_que_lanza(TimeoutError("timed out")),
        TimeoutError,
        id="timeout",
    ),
    pytest.param(
        _urlopen_que_responde(b'<a href="\xff.xsd">', "text/html; charset=utf-8"),
        UnicodeDecodeError,
        id="decodificacion",
    ),
]


class TestComparacionListadoSet:
    """Extraccion, diferencia, descarga y propagacion de fallas, sin red."""

    def test_listado_igual_al_local_no_reporta_nada(self) -> None:
        locales = _esquemas_locales()
        html = _listado_html("../", *sorted(locales))
        assert _esquemas_publicados(html) == locales
        assert _esquemas_nuevos(_esquemas_publicados(html), locales) == []

    def test_xsd_publicado_que_falta_se_reporta_ordenado(self) -> None:
        locales = {"DE_v150.xsd", "Evento_v150.xsd"}
        html = _listado_html("Evento_v160.xsd", "DE_v150.xsd", "DE_v160.xsd")
        nuevos = _esquemas_nuevos(_esquemas_publicados(html), locales)
        assert nuevos == ["DE_v160.xsd", "Evento_v160.xsd"]
        mensaje = _mensaje_esquemas_nuevos(nuevos)
        assert "DE_v160.xsd, Evento_v160.xsd" in mensaje

    def test_xsd_que_solo_existe_localmente_se_ignora(self) -> None:
        html = _listado_html("DE_v150.xsd")
        locales = {"DE_v150.xsd", "Solo_local_v100.xsd"}
        assert _esquemas_nuevos(_esquemas_publicados(html), locales) == []

    def test_enlaces_que_no_son_xsd_se_ignoran(self) -> None:
        html = _listado_html("../", "leeme.txt", "DE_v150.xsd.bak", "v150/")
        assert _esquemas_publicados(html) == set()

    def test_enlace_con_ruta_se_reduce_al_nombre(self) -> None:
        html = _listado_html("/sifen/xsd/DE_v160.xsd")
        assert _esquemas_publicados(html) == {"DE_v160.xsd"}

    @pytest.mark.parametrize(("urlopen_falso", "tipo_error"), _FALLAS_DE_DESCARGA)
    def test_falla_de_descarga_deja_la_deteccion_en_rojo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        urlopen_falso: Callable[..., _RespuestaFalsa],
        tipo_error: type[BaseException],
    ) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)

        with pytest.raises(tipo_error):
            try:
                _verificar_listado_set()
            except pytest.skip.Exception:
                pytest.fail(
                    "una falla de la descarga omitio la deteccion; debe fallar"
                )

    @pytest.mark.parametrize(
        ("valor", "activada"),
        [
            (None, False),
            ("", False),
            ("0", False),
            ("false", False),
            ("1", True),
            ("true", True),
        ],
    )
    def test_activacion_por_variable_de_entorno(
        self, valor: str | None, activada: bool
    ) -> None:
        assert _deteccion_activada(valor) is activada

    def test_descarga_verifica_tls_y_decodifica_con_el_charset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llamadas: list[tuple[urllib.request.Request, float, ssl.SSLContext]] = []
        respuesta = _RespuestaFalsa(
            _listado_html("Año_v150.xsd").encode("latin-1"),
            "text/html;charset=ISO-8859-1",
        )

        def urlopen_falso(
            pedido: urllib.request.Request,
            *,
            timeout: float,
            context: ssl.SSLContext,
        ) -> _RespuestaFalsa:
            llamadas.append((pedido, timeout, context))
            return respuesta

        monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)

        html = _descargar_listado_set()

        assert _esquemas_publicados(html) == {"Año_v150.xsd"}
        assert respuesta.cerrada
        ((pedido, timeout, contexto),) = llamadas
        assert pedido.full_url == URL_LISTADO_SET
        assert pedido.get_header("User-agent") == AGENTE_HTTP
        assert timeout == TIEMPO_ESPERA_S
        assert contexto.verify_mode == ssl.CERT_REQUIRED
        assert contexto.check_hostname is True


# ---------------------------------------------------------------------------
# Deteccion de XSD nuevos publicados por la SET (red)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _deteccion_activada(os.environ.get(VARIABLE_ACTIVACION)),
    reason=(
        f"consulta a la SET desactivada; definir {VARIABLE_ACTIVACION}=1 "
        "para buscar XSD nuevos"
    ),
)
class TestSchemaUpdates:
    """Compara el listado publico de la SET con los XSD del repositorio."""

    def test_detecta_esquemas_nuevos_en_set(self) -> None:
        _verificar_listado_set()
