-- ============================================================================
-- CDSS Anemia Infantil · Migración 012 (Sprint 2, parte G: pendiente P4)
-- asistencia.fragmento_recuperado.origen: RERANKER (seleccionado por la recuperación, el valor
-- de siempre) o PUNTERO (agregado porque otro fragmento enviado remite a esa tabla, según una
-- regla de backend/app/rag/punteros.yaml). Un fragmento agregado que no estaba entre los
-- candidatos de la fusión no tiene posición ni puntaje RRF: posicion_rrf y puntaje_rrf admiten
-- NULL solo con origen PUNTERO (restricción fragmento_recuperado_rrf_check). Un fragmento con
-- origen PUNTERO siempre se envía al modelo.
-- La vista asistencia.v_auditoria_consulta agrega el origen a cada fragmento enviado y los
-- ordena por etiqueta (el agregado no tiene posición final), con las mismas columnas.
-- Los permisos de tabla vigentes cubren la columna nueva (INSERT y SELECT de
-- rol_app_generacion). Es idempotente. Replicada en db/init/01_esquema.sql. La vista no se
-- redefine si ya tiene la forma de la migración 014.
-- ============================================================================

SET client_min_messages = warning;

ALTER TABLE asistencia.fragmento_recuperado ADD COLUMN IF NOT EXISTS origen VARCHAR(10) NOT NULL DEFAULT 'RERANKER';
COMMENT ON COLUMN asistencia.fragmento_recuperado.origen IS 'RERANKER (seleccionado por la recuperación) o PUNTERO (agregado porque otro fragmento enviado remite a esa tabla, backend/app/rag/punteros.yaml).';

ALTER TABLE asistencia.fragmento_recuperado DROP CONSTRAINT IF EXISTS fragmento_recuperado_origen_check;
ALTER TABLE asistencia.fragmento_recuperado ADD CONSTRAINT fragmento_recuperado_origen_check
  CHECK (origen IN ('RERANKER', 'PUNTERO') AND (origen = 'RERANKER' OR enviado_al_llm));

ALTER TABLE asistencia.fragmento_recuperado ALTER COLUMN posicion_rrf DROP NOT NULL;
ALTER TABLE asistencia.fragmento_recuperado ALTER COLUMN puntaje_rrf DROP NOT NULL;
ALTER TABLE asistencia.fragmento_recuperado DROP CONSTRAINT IF EXISTS fragmento_recuperado_rrf_check;
ALTER TABLE asistencia.fragmento_recuperado ADD CONSTRAINT fragmento_recuperado_rrf_check
  CHECK (origen = 'PUNTERO' OR (posicion_rrf IS NOT NULL AND puntaje_rrf IS NOT NULL));
COMMENT ON COLUMN asistencia.fragmento_recuperado.posicion_rrf IS 'Posición tras la fusión Reciprocal Rank Fusion (3.3); NULL solo en un fragmento con origen PUNTERO que no era candidato.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.puntaje_rrf IS 'Puntaje de la fusión RRF; NULL solo en un fragmento con origen PUNTERO que no era candidato.';

-- Desde la migración 014 la vista tiene más columnas (CREATE OR REPLACE no admite quitarlas):
-- si ya tiene la forma de 014, no se vuelve a definir aquí.
DO $migracion$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'asistencia' AND table_name = 'v_auditoria_consulta'
                    AND column_name = 'modo_prueba') THEN
    EXECUTE $vista$
CREATE OR REPLACE VIEW asistencia.v_auditoria_consulta AS
SELECT q.id_consulta, q.fecha_hora_inicio, u.nombre_usuario, q.estado, q.numero_intentos,
       q.latencia_total_ms, q.confirma_tamizaje_no_vigente, i.numero_intento, i.modelo_llm, i.tokens_entrada, i.tokens_salida,
       i.costo_usd, i.solicitud_enviada, i.valida_citas, i.valida_consistencia, i.valida_evidencia,
       i.resultado,
       (SELECT jsonb_agg(jsonb_build_object('etiqueta', f.etiqueta_cita,
                                            'puntaje', f.puntaje_reranker,
                                            'origen', f.origen) ORDER BY f.etiqueta_cita)
          FROM asistencia.fragmento_recuperado f
         WHERE f.id_intento = i.id_intento AND f.enviado_al_llm) AS fragmentos_enviados
FROM asistencia.consulta q
JOIN seguridad.usuario u ON u.id_usuario = q.id_usuario
LEFT JOIN asistencia.intento_generacion i ON i.id_consulta = q.id_consulta
$vista$;
  END IF;
END
$migracion$;
