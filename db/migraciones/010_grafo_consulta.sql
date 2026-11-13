-- ============================================================================
-- CDSS Anemia Infantil · Migración 010 (Sprint 2, parte D1: grafo de la consulta)
-- 1. asistencia.consulta.estado admite dos estados finales propios:
--    TAMIZAJE_NO_VIGENTE (el profesional no confirmó continuar con un tamizaje vencido;
--    si confirma, se registra una consulta nueva con id_consulta_previa) y
--    SOLICITUD_BLOQUEADA (el control previo detectó identificadores y no se envió nada).
-- 2. asistencia.fragmento_recuperado guarda los 20 primeros candidatos de la fusión: los
--    que no pasan por el reranker quedan con puntaje_reranker y posicion_final en NULL.
-- 3. Tiempos por etapa en JSONB: consulta.tiempos_ms (por nodo, total y hasta el primer
--    evento), que escribe el nodo salida con cdss_clinica, e intento_generacion.tiempos_ms
--    (por intento), que escribe cdss_generacion. Los permisos de tabla vigentes ya cubren
--    las columnas nuevas (UPDATE de consulta para rol_app_clinica; INSERT y UPDATE de
--    intento_generacion para rol_app_generacion). rol_app_generacion no recibe lectura de
--    consulta.tiempos_ms porque no la necesita.
-- Es idempotente. Replicada en db/init/01_esquema.sql.
-- ============================================================================

SET client_min_messages = warning;

ALTER TABLE asistencia.consulta DROP CONSTRAINT IF EXISTS consulta_estado_check;
ALTER TABLE asistencia.consulta ADD CONSTRAINT consulta_estado_check CHECK (estado IN (
  'EN_PROCESO','VERIFICADA','DATOS_FALTANTES','FUERA_DE_DOMINIO','EVIDENCIA_INSUFICIENTE','ERROR',
  'TAMIZAJE_NO_VIGENTE','SOLICITUD_BLOQUEADA'));
COMMENT ON COLUMN asistencia.consulta.estado IS 'EN_PROCESO, VERIFICADA, DATOS_FALTANTES, FUERA_DE_DOMINIO, EVIDENCIA_INSUFICIENTE, ERROR, TAMIZAJE_NO_VIGENTE o SOLICITUD_BLOQUEADA.';

ALTER TABLE asistencia.consulta ADD COLUMN IF NOT EXISTS tiempos_ms JSONB;
COMMENT ON COLUMN asistencia.consulta.tiempos_ms IS 'Tiempos de la consulta en milisegundos: por nodo del grafo, espera en cola, hasta el primer evento y total.';

ALTER TABLE asistencia.intento_generacion ADD COLUMN IF NOT EXISTS tiempos_ms JSONB;
COMMENT ON COLUMN asistencia.intento_generacion.tiempos_ms IS 'Tiempos del intento en milisegundos: recuperación, protección, llamada al modelo, verificación y espera en cola.';

ALTER TABLE asistencia.fragmento_recuperado ALTER COLUMN puntaje_reranker DROP NOT NULL;
ALTER TABLE asistencia.fragmento_recuperado ALTER COLUMN posicion_final DROP NOT NULL;
COMMENT ON COLUMN asistencia.fragmento_recuperado.puntaje_reranker IS 'Puntaje del reranker clínico (3.4); NULL si el candidato no pasó por el reranker.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.posicion_final IS 'Posición tras el reranking; NULL si el candidato no pasó por el reranker.';
