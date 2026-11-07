-- ============================================================================
-- CDSS Anemia Infantil · Migración 005 (Sprint 2: parámetros definitivos de la
-- recuperación, elegidos con las mediciones de la parte B)
-- Reranker bge-reranker-v2-m3 en ONNX int8 con 8 candidatos de hasta 256 tokens,
-- UMBRAL_RELEVANCIA recalibrado con los puntajes del motor int8 (baja de 0,60) y
-- UMBRAL_DOMINIO calibrado con las consultas de referencia (sube de 0,50).
-- Cada valor se registra como versión nueva: la vigente se cierra con
-- vigente_hasta y la nueva empieza en el mismo instante. Solo se aplica si el
-- valor vigente es todavía el inicial del plan: es idempotente y no pisa un
-- cambio hecho después. Replicada al final de db/init/02_catalogos.sql.
-- ============================================================================

SET client_min_messages = warning;

WITH nuevos (clave, valor_inicial, valor, descripcion) AS (VALUES
  ('CANDIDATOS_RERANKER',   '20',   '8',    'Candidatos de la fusión RRF que evalúa el reranker (bge-reranker-v2-m3 ONNX int8)'),
  ('MAX_LONGITUD_RERANKER', '1024', '256',  'Tokens máximos de cada par consulta y fragmento en el reranker'),
  ('UMBRAL_RELEVANCIA',     '0.60', '0.15', 'Puntaje mínimo del reranker para considerar suficiente la evidencia (calibrado con el motor ONNX int8)'),
  ('UMBRAL_DOMINIO',        '0.50', '0.65', 'Similitud mínima con las consultas de referencia del dominio (calibrada con las consultas de referencia)')
),
cerrados AS (
  UPDATE configuracion.parametro_sistema p
     SET vigente_hasta = now()
    FROM nuevos n
   WHERE p.clave = n.clave AND p.vigente_hasta IS NULL AND p.valor = n.valor_inicial
  RETURNING p.clave, p.tipo_dato, p.valor_minimo, p.valor_maximo
)
INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, vigente_desde, modificado_por)
SELECT c.clave, n.valor, c.tipo_dato, c.valor_minimo, c.valor_maximo, n.descripcion, now(),
       '00000000-0000-0000-0000-000000000001'
FROM cerrados c
JOIN nuevos n USING (clave);
