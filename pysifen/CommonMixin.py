"""Mixin comum para todos os bindings do SIFEN."""
from pathlib import Path

from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig


class CommonMixin:
    """Mixin adicionado automaticamente pelo xsdata a todas as classes."""

    @classmethod
    def from_xml(cls, xml_string: str):
        """Deserializa um XML string em objeto Python."""
        parser = XmlParser()
        return parser.from_string(xml_string, cls)

    @classmethod
    def from_path(cls, file_path: str):
        """Deserializa um arquivo XML em objeto Python."""
        parser = XmlParser()
        return parser.from_path(Path(file_path), cls)

    def to_xml(self, pretty_print: bool = True) -> str:
        """Serializa o objeto Python em XML string."""
        config = SerializerConfig(
            pretty_print=pretty_print,
            xml_declaration=True,
            encoding="UTF-8",
        )
        serializer = XmlSerializer(config=config)
        return serializer.render(self)

    def validate_xml(self) -> list:
        """Valida o XML contra o schema XSD correspondente."""
        from pysifen.sdk.validation import validate_xml

        module = self.__class__.__module__
        parts = module.split(".")

        schema_family = "de"
        schema_version = "v150"
        # Exemplo esperado: pysifen.de.bindings.v150.fe_v141
        if len(parts) >= 4 and parts[0] == "pysifen":
            if parts[1]:
                schema_family = parts[1]
            if parts[3].startswith("v"):
                schema_version = parts[3]

        return validate_xml(
            self.to_xml(),
            schema_family=schema_family,
            schema_version=schema_version,
        )

    def sign_xml(self, xml, pkcs12_data, pkcs12_password, doc_id):
        """Assina o XML usando certificado PKCS12 (RSA-SHA256)."""
        try:
            from pysifen.assinatura import sign_xml
        except ImportError:
            raise ImportError(
                "Para assinar XML, instale: "
                "pip install sifen[sign]"
            )
        return sign_xml(xml, pkcs12_data, pkcs12_password, doc_id)
