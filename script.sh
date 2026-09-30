#!/bin/bash
set -e

echo "=== Gerando bindings do SIFEN ==="

# Documento Electrónico v150
echo "Gerando DE v150..."
xsdata generate kilasifen/engine/de/schemas/v150 \
    --package kilasifen.engine.de.bindings.v150

echo "=== Bindings gerados com sucesso ==="
