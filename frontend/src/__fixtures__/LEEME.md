# Fixtures del contrato de consultas

Los genera `backend/tests/test_e0_fixtures.py` (con `pytest`), con el cliente falso del modelo de
lenguaje, la guía de prueba de las pruebas del backend y los pacientes ficticios de `seed_demo`.
No los edite a mano: si el contrato cambia, vuelva a correr la prueba y revise el diff.

- `consulta_<estado>.ndjson`: el stream de `POST /api/pacientes/{id}/consultas`, una línea por evento.
- `resultado_<estado>.json`: la respuesta de `GET /api/consultas/{id}` de esa misma consulta.

Valores normalizados para que el diff muestre solo cambios del contrato: UUID en orden de aparición
(`00000000-0000-4000-8000-00000000000N`), tiempos en 100 ms (`transcurrido_ms` crece de 100 en 100),
fechas `2026-10-20T10:00:00-05:00`; en el resultado, la vigencia y su mensaje son los del evento `fin`.
Los puntajes salen del reranker falso y el umbral es el de las pruebas (0,05), no los reales (0,15).
`modo_prueba` es `true` en las consultas que llamaron al cliente falso. Contrato:
`docs/contrato_consultas.md`.

## Auditoría (M13, parte D1 del Sprint 3)

Los genera `backend/tests/test_d1_auditoria.py` con consultas sintéticas insertadas en la base de
pruebas (pacientes de `seed_demo`, sin el modelo de lenguaje). Contrato: `docs/contrato_auditoria.md`.

- `auditoria_indicadores.json`: `GET /api/auditoria/indicadores` (seis consultas reales en varios
  estados y una de prueba, que no cuenta). La ventana se fija en `2026-09-20` a `2026-10-20`.
- `auditoria_consultas.json`: `GET /api/auditoria/consultas` de un día con `incluir_pruebas=true`
  (una real con reintento, una de prueba y una fuera de dominio).
- `auditoria_detalle.json`: `GET /api/auditoria/consultas/{id}` de la consulta real, con dos
  intentos, la solicitud registrada y tres fragmentos (el último agregado por referencia).

UUID en orden de aparición y fechas pasadas a octubre de 2026. Si al generarlos hay otras
consultas de los últimos 30 días en la base de pruebas, la prueba se salta (los indicadores no
serían reproducibles).
