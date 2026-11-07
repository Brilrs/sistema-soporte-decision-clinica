-- ============================================================================
-- CDSS Anemia Infantil · Migración 004 (Sprint 2: parámetros del reranker)
-- Candidatos que pasan al reranker y longitud máxima en tokens de cada par
-- consulta y fragmento. Permiten aplicar la configuración elegida con las
-- mediciones de rendimiento sin cambiar el código. Los valores iniciales son los
-- del plan (20 candidatos y 1024 tokens). Solo inserta las claves que no existen:
-- es idempotente y no pisa un cambio hecho después.
-- ============================================================================

SET client_min_messages = warning;

INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, modificado_por)
SELECT v.clave, v.valor, v.tipo, v.vmin, v.vmax, v.descr, '00000000-0000-0000-0000-000000000001'
FROM (VALUES
  ('CANDIDATOS_RERANKER',   '20',   'ENTERO', 1,  100,  'Candidatos de la fusión RRF que evalúa el reranker'),
  ('MAX_LONGITUD_RERANKER', '1024', 'ENTERO', 64, 1024, 'Tokens máximos de cada par consulta y fragmento en el reranker')
) AS v(clave, valor, tipo, vmin, vmax, descr)
WHERE NOT EXISTS (SELECT 1 FROM configuracion.parametro_sistema p WHERE p.clave = v.clave);
