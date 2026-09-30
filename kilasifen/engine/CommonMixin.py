"""Mixin comum para todos os bindings do SIFEN."""
from functools import lru_cache
from pathlib import Path

from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig


@lru_cache(maxsize=1)
def _get_xml_parser() -> XmlParser:
    """Return a reusable XML parser instance."""
    return XmlParser()


@lru_cache(maxsize=2)
def _get_xml_serializer(pretty_print: bool) -> XmlSerializer:
    """Return a reusable XML serializer instance for the requested format."""
    config = SerializerConfig(
        xml_declaration=True,
        encoding="UTF-8",
        indent="  " if pretty_print else None,
    )
    return XmlSerializer(config=config)


class CommonMixin:
    """Mixin adicionado automaticamente pelo xsdata a todas as classes."""

    @classmethod
    def from_xml(cls, xml_string: str):
        """Deserializa um XML string em objeto Python."""
        return _get_xml_parser().from_string(xml_string, cls)

    @classmethod
    def from_path(cls, file_path: str):
        """Deserializa um arquivo XML em objeto Python."""
        return _get_xml_parser().from_path(Path(file_path), cls)

    def to_xml(self, pretty_print: bool = True) -> str:
        """Serializa o objeto Python em XML string."""
        return _get_xml_serializer(pretty_print).render(self)

    def validate_xml(self) -> list:
        """Valida o XML contra o schema XSD correspondente."""
        from kilasifen.engine.sdk.validation import validate_xml

        module = self.__class__.__module__
        parts = module.split(".")

        schema_family = "de"
        schema_version = "v150"
        # Exemplo esperado: kilasifen.engine.de.bindings.v150.fe_v141
        if len(parts) >= 5 and parts[:2] == ["kilasifen", "engine"]:
            if parts[2]:
                schema_family = parts[2]
            if parts[4].startswith("v"):
                schema_version = parts[4]

        return validate_xml(
            self.to_xml(),
            schema_family=schema_family,
            schema_version=schema_version,
        )

    def sign_xml(self, xml, pkcs12_data, pkcs12_password, doc_id):
        """Assina o XML usando certificado PKCS12 (RSA-SHA256)."""
        try:
            from kilasifen.engine.assinatura import sign_xml
        except ImportError:
            raise ImportError(
                "Para assinar XML, instale: "
                "pip install sifen[sign]"
            )
        return sign_xml(xml, pkcs12_data, pkcs12_password, doc_id)
