-- ============================================================================
-- CDSS Anemia Infantil · Migración 007 (Sprint 2: respuesta del modelo sin cortes)
-- En la corrida real de la parte C, tres respuestas llegaron al límite de 1000 tokens
-- de salida en los dos intentos. MAX_TOKENS_SALIDA sube a 1500 y VERSION_PROMPT pasa a
-- v1.1, que pide una respuesta compacta (resumen breve, hasta 3 pasos y un extracto
-- corto por fragmento).
-- Cada valor se registra como versión nueva: la vigente se cierra con vigente_hasta y
-- la nueva empieza en el mismo instante. Solo se aplica si el valor vigente es todavía
-- el anterior: es idempotente y no pisa un cambio hecho después. Replicada al final de
-- db/init/02_catalogos.sql.
-- ============================================================================

SET client_min_messages = warning;

WITH nuevos (clave, valor_anterior, valor, descripcion) AS (VALUES
  ('MAX_TOKENS_SALIDA', '1000', '1500', 'Longitud máxima de la respuesta del modelo, incluido el razonamiento'),
  ('VERSION_PROMPT',    'v1.0', 'v1.1', 'Versión vigente del prompt clínico (v1.1: respuesta compacta)')
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
