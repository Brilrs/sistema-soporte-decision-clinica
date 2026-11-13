-- ============================================================================
-- CDSS Anemia Infantil · Migración 009 (Sprint 2, parte C2: peso de la edad)
-- BONIFICACION_EDAD pasa de 0 a 0.7, calibrado solo con las consultas de ajuste (R)
-- con la recuperación real en la versión 5 de las guías (19 de 20 frente a 18 de 20
-- con 0, 0.1, 0.3 y 0.5). Con 0.5 se pierden fragmentos de la edad del paciente en los
-- casos c y e de la prueba de punta a punta (docs/mediciones_sprint2.md, parte C2).
-- El valor vigente se cierra con vigente_hasta y el nuevo empieza en el mismo instante.
-- Solo se aplica si el valor vigente es todavía 0: es idempotente y no pisa un cambio
-- hecho después. Replicada al final de db/init/02_catalogos.sql.
-- ============================================================================

SET client_min_messages = warning;

WITH nuevos (clave, valor_anterior, valor, descripcion) AS (VALUES
  ('BONIFICACION_EDAD', '0', '0.7', 'Peso de la edad del paciente en la fusión RRF: multiplica por (1 + peso) el puntaje de los fragmentos cuyo rango incluye la edad y por (1 - peso) el de los que la excluyen (0.7 calibrado en C2)')
),
cerrados AS (
  UPDATE configuracion.parametro_sistema p
     SET vigente_hasta = now()
    FROM nuevos n
   WHERE p.clave = n.clave AND p.vigente_hasta IS NULL AND p.valor = n.valor_anterior
  RETURNING p.clave, p.tipo_dato, p.valor_minimo, p.valor_maximo
)
INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, vigente_desde, modificado_por)
SELECT c.clave, n.valor, c.tipo_dato, c.valor_minimo, c.valor_maximo, n.descripcion, now(),
       '00000000-0000-0000-0000-000000000001'
FROM cerrados c
JOIN nuevos n USING (clave);
