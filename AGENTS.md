# AGENTS.md — Reglas de Ejecución (Kila SIFEN)

1. Escribir solo código mantenible: nombres claros, funciones cortas, sin duplicación, sin “parches rápidos”.
2. Evitar escribir código de mierda: nada de hacks ocultos, lógica mezclada, bloques gigantes ni magia sin explicación.
3. Todo cambio debe incluir validación: test nuevo/ajustado o evidencia técnica de que no rompe comportamiento.
4. Commit obligatorio después de cada cambio terminado. No se pregunta, se hace commit.
5. Backend/API en capas: `router -> service -> repository` (o equivalente), sin saltar capas.
6. Contratos API claros: request/response tipados, validación estricta de entrada, errores consistentes.
7. No hardcodear secretos, tokens, certificados ni endpoints sensibles; usar config/env.
8. Mantener compatibilidad: no romper API pública sin documentar migración.
9. Logs útiles y limpios: contexto suficiente para debug, sin exponer datos sensibles.
10. Si algo no está claro, documentar la decisión en el PR/commit y seguir avanzando con criterio técnico.
