# Public API estable

La interfaz pública estable de `kilasifen.engine` está concentrada en la fachada top-level del paquete.

## Contrato

Se considera API pública estable lo siguiente:

- `kilasifen.engine.__version__`
- `kilasifen.engine.sign_xml`
- `kilasifen.engine.PRODUCCION`
- `kilasifen.engine.TEST`
- `kilasifen.engine.ENDPOINTS`
- `kilasifen.engine.get_endpoint`
- `kilasifen.engine.TransmissaoDE`
- `kilasifen.engine.ConsultaSIFEN`
- `kilasifen.engine.TransmissaoEvento`

Estos símbolos se importan desde `kilasifen.engine` sin necesidad de conocer la estructura interna del paquete.

## No estable

No se considera parte de la API pública estable:

- `kilasifen.engine.de.bindings.*`
- módulos de `kilasifen.engine.transmissao.*` usados internamente para implementación
- detalles de nombres de clases, funciones o constantes que no estén reexportados desde `kilasifen.engine`

## Ejemplos

### Firma

```python
from kilasifen.engine import sign_xml
```

### Ambientes y endpoints

```python
from kilasifen.engine import PRODUCCION, TEST, get_endpoint

url = get_endpoint(TEST, "cons_de")
```

### Transmisión

```python
from kilasifen.engine import ConsultaSIFEN, TransmissaoDE, TransmissaoEvento
```

## Criterios de compatibilidad

- No romper imports top-level existentes.
- No exigir imports desde submódulos para el uso habitual.
- Mantener `__all__` alineado con los símbolos exportados.
- Evitar cambios incompatibles en los bindings generados bajo `kilasifen.engine.de.bindings`.

## Platform separation

This document is for `kilasifen.engine` public API only.

The `kilasifen` platform API and operations are documented in:

- `docs/architecture/kila-api-contract.md`
- `docs/architecture/kila-platform.md`
- `docs/operations/deployment-compose.md`
