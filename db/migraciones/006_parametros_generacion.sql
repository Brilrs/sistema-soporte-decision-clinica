-- ============================================================================
-- CDSS Anemia Infantil · Migración 006 (Sprint 2: parámetros de la generación,
-- confirmados con la API de Anthropic en la parte C)
-- claude-sonnet-5-5 razona de forma adaptativa por defecto y no admite desactivar
-- el razonamiento; sus tokens cuentan dentro de MAX_TOKENS_SALIDA. between_tools
-- es el valor más bajo: sin herramientas, el modelo no razona antes de responder.
-- El esfuerzo controla la profundidad, la latencia y el costo de la respuesta.
-- Agrega además tokens_razonamiento a intento_generacion: tokens_salida ya los
-- incluye (se cobran como salida), pero se registran aparte para controlar el gasto.
-- Solo inserta los parámetros que aún no tienen valor vigente: es idempotente.
-- Replicada en db/init/01_esquema.sql (columna) y al final de 02_catalogos.sql.
-- ============================================================================

SET client_min_messages = warning;

INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, modificado_por)
SELECT v.clave, v.valor, 'TEXTO', NULL, NULL, v.descr, '00000000-0000-0000-0000-000000000001'
FROM (VALUES
  ('RAZONAMIENTO_LLM', 'between_tools', 'Configuración de razonamiento del modelo de lenguaje (between_tools o adaptive)'),
  ('ESFUERZO_LLM',     'medium',        'Esfuerzo del modelo de lenguaje (low, medium o high)')
) AS v(clave, valor, descr)
WHERE NOT EXISTS (SELECT 1 FROM configuracion.parametro_sistema p
                   WHERE p.clave = v.clave AND p.vigente_hasta IS NULL);

ALTER TABLE asistencia.intento_generacion
  ADD COLUMN IF NOT EXISTS tokens_razonamiento INTEGER CHECK (tokens_razonamiento >= 0);
COMMENT ON COLUMN asistencia.intento_generacion.tokens_razonamiento IS
  'Tokens de razonamiento del modelo en el intento; ya están incluidos en tokens_salida.';
