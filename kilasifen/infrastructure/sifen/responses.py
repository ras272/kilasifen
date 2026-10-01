"""Readers for SIFEN answers that the generated bindings cannot hold.

- siRecepDE (``rRetEnviDe``): the XSD puts ``dEstRes`` and ``dProtAut`` in
  ``rProtDe`` (protProcesDE_v150.xsd:98-111) while the MT v150 (PP050/PP051
  under PP05 p. 46; example §7.4 p. 36) shows them inside ``gResProc``. Both
  layouts are accepted, so the answer is read with ElementTree by local
  names instead of the binding, which would refuse the MT layout.
- siConsDE (``rEnviConsDeResponse``): ``xContenDE`` is ``xs:string``
  (WS_SiConsDE_v141.xsd:49) and carries the container ``rContDe{rDE,
  dProtAut, xContEv 0-n}`` (MT v150 Schemas XML 11-12, pp. 51-52), whose
  XSD SET did not publish. It is accepted escaped as text or embedded as
  elements; its exact form is NO DETERMINADO.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree as ET

from kilasifen.engine.sdk.errors import SifenUnexpectedResponseError
from kilasifen.infrastructure.sifen.de_facts import parse_sifen_datetime

_RECEPTION_ROOT = "rRetEnviDe"

#: Event groups of Evento_v150.xsd (``gGroupTiEvt``) and the name the
#: platform reports for each.
EVENT_KINDS = {
    "rGeVeCan": "cancelacion",
    "rGeVeInu": "inutilizacion",
    "rGeVeNotRec": "notificacion_recepcion",
    "rGeVeConf": "conformidad",
    "rGeVeDisconf": "disconformidad",
    "rGeVeDescon": "desconocimiento",
    "rGeVeEnd": "endoso",
    "rGeVeTr": "transporte",
    "rGEveNom": "nominacion",
}
CANCELLATION_EVENT_KIND = EVENT_KINDS["rGeVeCan"]


@dataclass(frozen=True, slots=True)
class SifenMessage:
    """One ``gResProc``: result code and message."""

    code: str
    message: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class ReceptionAnswer:
    """What one ``rRetEnviDe`` says, before the platform classifies it."""

    state_text: str | None
    protocol: str | None
    processed_at: datetime | None
    messages: tuple[SifenMessage, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(message.code for message in self.messages)


@dataclass(frozen=True, slots=True)
class RegisteredEvent:
    """One event of ``xContEv``: what it is, on which CDC, its protocol."""

    kind: str
    cdc: str | None
    protocol: str | None
    state_text: str | None


@dataclass(frozen=True, slots=True)
class DocumentContainer:
    """Content of ``xContenDE``: the DTE, its protocol and its events."""

    document_xml: str | None
    protocol: str | None
    events: tuple[RegisteredEvent, ...]

    def has_cancellation(self, cdc: str) -> bool:
        return self.cancellation_for(cdc) is not None

    def cancellation_for(self, cdc: str) -> RegisteredEvent | None:
        for event in self.events:
            if event.kind != CANCELLATION_EVENT_KIND:
                continue
            if event.cdc in (None, cdc):
                return event
        return None


def read_reception_answer(body: bytes | str) -> ReceptionAnswer:
    """Read an ``rRetEnviDe`` body in the XSD or the MT layout.

    Raises:
        SifenUnexpectedResponseError: if ``body`` is not XML or not an
            ``rRetEnviDe`` (SOAP Fault, proxy page): the outcome is unknown.
    """

    raw = body if isinstance(body, bytes) else body.encode("utf-8")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SifenUnexpectedResponseError(
            expected_root=_RECEPTION_ROOT,
            actual_root="invalid_xml",
            raw_body=raw,
        ) from exc
    root_name = _local(root.tag)
    if root_name != _RECEPTION_ROOT:
        raise SifenUnexpectedResponseError(
            expected_root=_RECEPTION_ROOT,
            actual_root=root_name,
            code=_first_text(root, "dCodRes"),
            response_message=_first_text(root, "dMsgRes"),
            raw_body=raw,
        )

    protocol_node = _first_element(root, "rProtDe")
    if protocol_node is None:
        protocol_node = root
    results = _children(protocol_node, "gResProc")
    return ReceptionAnswer(
        state_text=_child_text(protocol_node, "dEstRes")
        or _first_in(results, "dEstRes"),
        protocol=_child_text(protocol_node, "dProtAut")
        or _first_in(results, "dProtAut"),
        processed_at=parse_sifen_datetime(
            _child_text(protocol_node, "dFecProc") or _child_text(root, "dFecProc")
        ),
        messages=tuple(
            message for message in map(_message, results) if message.code
        ),
    )


def read_document_container(response_body: bytes | str) -> DocumentContainer | None:
    """Read ``xContenDE`` out of an ``rEnviConsDeResponse`` body.

    Returns ``None`` when there is no container or it cannot be read.
    """

    raw = response_body if isinstance(response_body, bytes) else (
        response_body.encode("utf-8")
    )
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    content = _first_element(root, "xContenDE")
    if content is None:
        return None
    container = _container_root(content)
    if container is None:
        return None
    if _local(container.tag) == "rDE":
        return DocumentContainer(
            document_xml=_serialize(container), protocol=None, events=()
        )

    document = _first_element(container, "rDE")
    return DocumentContainer(
        document_xml=_serialize(document) if document is not None else None,
        protocol=_child_text(container, "dProtAut"),
        events=tuple(
            event
            for node in _children(container, "xContEv")
            for event in _read_registered_events(node)
        ),
    )


def _container_root(content: ET.Element) -> ET.Element | None:
    embedded = [child for child in content if isinstance(child.tag, str)]
    if embedded:
        return embedded[0]
    text = (content.text or "").strip()
    if not text:
        return None
    try:
        return ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return None


def _read_registered_events(node: ET.Element) -> list[RegisteredEvent]:
    """Read the events of one ``xContEv`` (embedded or escaped)."""

    holder = node
    if not [child for child in node if isinstance(child.tag, str)]:
        parsed = _container_root(node)
        if parsed is None:
            return []
        holder = parsed
    answer = _first_element(holder, "rResEnviEventoDe")
    protocol = _first_text(answer, "dProtAut") if answer is not None else None
    state_text = _first_text(answer, "dEstRes") if answer is not None else None
    events: list[RegisteredEvent] = []
    for element in holder.iter():
        if not isinstance(element.tag, str):
            continue
        kind = EVENT_KINDS.get(_local(element.tag))
        if kind is None:
            continue
        events.append(
            RegisteredEvent(
                kind=kind,
                cdc=_child_text(element, "Id"),
                protocol=protocol,
                state_text=state_text,
            )
        )
    return events


def _message(node: ET.Element) -> SifenMessage:
    return SifenMessage(
        code=_child_text(node, "dCodRes") or "",
        message=_child_text(node, "dMsgRes"),
    )


def _serialize(element: ET.Element) -> str:
    return ET.tostring(element, encoding="unicode")


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _children(node: ET.Element, local_name: str) -> list[ET.Element]:
    return [
        child
        for child in node
        if isinstance(child.tag, str) and _local(child.tag) == local_name
    ]


def _child_text(node: ET.Element, local_name: str) -> str | None:
    for child in _children(node, local_name):
        value = (child.text or "").strip()
        if value:
            return value
    return None


def _first_in(nodes: list[ET.Element], local_name: str) -> str | None:
    for node in nodes:
        value = _child_text(node, local_name)
        if value:
            return value
    return None


def _first_element(root: ET.Element, local_name: str) -> ET.Element | None:
    for element in root.iter():
        if isinstance(element.tag, str) and _local(element.tag) == local_name:
            return element
    return None


def _first_text(root: ET.Element, local_name: str) -> str | None:
    element = _first_element(root, local_name)
    if element is None:
        return None
    value = (element.text or "").strip()
    return value or None
