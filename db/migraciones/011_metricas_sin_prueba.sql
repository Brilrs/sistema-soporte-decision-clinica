-- ============================================================================
-- CDSS Anemia Infantil · Migración 011 (Sprint 2, parte F1: P2 de cambios_respecto_al_OE2.md)
-- Las consultas de prueba quedan fuera de las métricas agregadas. Una consulta es de prueba
-- si alguno de sus intentos lo generó el cliente falso del modelo de lenguaje
-- (asistencia.intento_generacion.modelo_llm = 'modelo-falso', la constante MODELO_FALSO de
-- backend/app/rag/cliente_llm.py; CDSS_LLM=falso o pruebas). Es la misma regla con la que la
-- API marca modo_prueba. Se redefinen, con las mismas columnas:
-- 1. asistencia.v_consultas_sin_evidencia (M11): solo consultas reales.
-- 2. asistencia.v_indicadores_operativos: consultas, p90, reintentos, porcentaje de evidencia
--    insuficiente y costo de la API, sin consultas ni intentos de prueba.
-- 3. conocimiento.v_uso_documento: las citas de los últimos 30 días cuentan solo las de
--    recomendaciones de consultas reales.
-- Los permisos de las vistas se conservan (CREATE OR REPLACE VIEW no los cambia).
-- Es idempotente. Replicada en db/init/01_esquema.sql.
-- ============================================================================

SET client_min_messages = warning;

CREATE OR REPLACE VIEW asistencia.v_indicadores_operativos AS
SELECT count(*) AS consultas,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY latencia_total_ms)
         FILTER (WHERE numero_intentos <= 1) AS p90_flujo_normal_ms,
       round(100.0 * count(*) FILTER (WHERE numero_intentos = 2) / NULLIF(count(*), 0), 1) AS pct_con_reintento,
       round(100.0 * count(*) FILTER (WHERE estado = 'EVIDENCIA_INSUFICIENTE') / NULLIF(count(*), 0), 1) AS pct_evidencia_insuficiente,
       (SELECT coalesce(sum(costo_usd), 0) FROM asistencia.intento_generacion
         WHERE fecha_hora >= now() - interval '30 days'
           AND modelo_llm IS DISTINCT FROM 'modelo-falso') AS costo_api_usd
FROM asistencia.consulta q
WHERE fecha_hora_inicio >= now() - interval '30 days'
  AND NOT EXISTS (SELECT 1 FROM asistencia.intento_generacion p
                   WHERE p.id_consulta = q.id_consulta AND p.modelo_llm = 'modelo-falso');

CREATE OR REPLACE VIEW conocimiento.v_uso_documento AS
SELECT d.id_documento, d.titulo, d.nivel, d.estado, d.total_fragmentos,
       count(ce.id_cita) FILTER (WHERE r.fecha_generacion >= now() - interval '30 days'
                                   AND NOT EXISTS (SELECT 1 FROM asistencia.intento_generacion p
                                                    WHERE p.id_consulta = r.id_consulta
                                                      AND p.modelo_llm = 'modelo-falso')) AS citas_30_dias
FROM conocimiento.documento_fuente d
LEFT JOIN conocimiento.fragmento f ON f.id_documento = d.id_documento
LEFT JOIN asistencia.cita_evidencia ce ON ce.id_fragmento = f.id_fragmento
LEFT JOIN asistencia.recomendacion r ON r.id_recomendacion = ce.id_recomendacion
GROUP BY d.id_documento;

CREATE OR REPLACE VIEW asistencia.v_consultas_sin_evidencia AS
SELECT q.id_consulta, q.fecha_hora_inicio, i.consulta_reformulada, i.relevancia_maxima, i.umbral_relevancia
FROM asistencia.consulta q
JOIN asistencia.intento_generacion i ON i.id_consulta = q.id_consulta AND i.numero_intento = q.numero_intentos
WHERE q.estado = 'EVIDENCIA_INSUFICIENTE'
  AND NOT EXISTS (SELECT 1 FROM asistencia.intento_generacion p
                   WHERE p.id_consulta = q.id_consulta AND p.modelo_llm = 'modelo-falso');

COMMENT ON VIEW asistencia.v_consultas_sin_evidencia IS 'Consultas reales (sin las de prueba del cliente falso) cerradas con evidencia insuficiente, para evaluar la incorporación de nuevas guías (M11).';
COMMENT ON VIEW asistencia.v_indicadores_operativos IS 'Indicadores de los últimos 30 días sin las consultas de prueba del cliente falso.';
COMMENT ON VIEW conocimiento.v_uso_documento IS 'Uso de cada guía: citas de los últimos 30 días en recomendaciones de consultas reales.';
