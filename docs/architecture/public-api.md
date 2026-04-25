# Public API estable

La interfaz pública estable de `pysifen` está concentrada en la fachada top-level del paquete.

## Contrato

Se considera API pública estable lo siguiente:

- `pysifen.__version__`
- `pysifen.sign_xml`
- `pysifen.PRODUCCION`
- `pysifen.TEST`
- `pysifen.ENDPOINTS`
- `pysifen.get_endpoint`
- `pysifen.TransmissaoDE`
- `pysifen.ConsultaSIFEN`
- `pysifen.TransmissaoEvento`

Estos símbolos se importan desde `pysifen` sin necesidad de conocer la estructura interna del paquete.

## No estable

No se considera parte de la API pública estable:

- `pysifen.de.bindings.*`
- módulos de `pysifen.transmissao.*` usados internamente para implementación
- detalles de nombres de clases, funciones o constantes que no estén reexportados desde `pysifen`

## Ejemplos

### Firma

```python
from pysifen import sign_xml
```

### Ambientes y endpoints

```python
from pysifen import PRODUCCION, TEST, get_endpoint

url = get_endpoint(TEST, "cons_de")
```

### Transmisión

```python
from pysifen import ConsultaSIFEN, TransmissaoDE, TransmissaoEvento
```

## Criterios de compatibilidad

- No romper imports top-level existentes.
- No exigir imports desde submódulos para el uso habitual.
- Mantener `__all__` alineado con los símbolos exportados.
- Evitar cambios incompatibles en los bindings generados bajo `pysifen.de.bindings`.

## Platform separation

This document is for `pysifen` public API only.

The `kilasifen` platform API and operations are documented in:

- `docs/architecture/kila-api-contract.md`
- `docs/architecture/kila-platform.md`
- `docs/operations/deployment-compose.md`
