-- ============================================================================
-- CDSS Anemia Infantil · Migración 014 (Sprint 3, parte D1: auditoría M13, HU13)
-- Vistas de solo lectura para el rol del auditor (cdss_auditor), que no tiene permisos sobre las
-- tablas clínicas: solo lee estas vistas y el esquema auditoria. Una consulta es de prueba si
-- alguno de sus intentos lo generó el cliente falso (modelo_llm = 'modelo-falso', la regla de la
-- migración 011 y de modo_prueba en la API).
-- 1. asistencia.v_auditoria_consulta (una fila por intento): agrega al final modo_prueba, la
--    versión del prompt, los tokens de razonamiento, la latencia del modelo, la búsqueda
--    (tipo, candidatos, relevancia y umbral), el control previo y el hash de la solicitud y la
--    fecha de fin de la consulta. solicitud_enviada solo se muestra si el control previo la
--    aprobó (control_identificadores = true): una solicitud bloqueada nunca se guarda, y la vista
--    no la expondría aunque quedara una. Los fragmentos enviados traen además la posición final y
--    el documento, la sección y las páginas de la guía.
-- 2. asistencia.v_auditoria_lista (nueva, una fila por consulta, paginable): usuario, estado,
--    intentos, latencia, modo_prueba, modelo y prompt del último intento, tokens y costo.
-- 3. asistencia.v_indicadores_operativos: mismas columnas iniciales (consultas, p90 del flujo
--    normal, porcentaje con reintento y con evidencia insuficiente, costo) y, al final, p50 y p90
--    de todas las consultas, conteos por estado, porcentajes de verificadas y evaluadas, tokens y
--    la ventana. Sigue sin consultas de prueba y con la ventana de 30 días.
-- Ninguna vista lleva la identidad del paciente, texto_consulta, observaciones del tamizaje ni la
-- nota de la decisión. CREATE OR REPLACE VIEW conserva los permisos; la vista nueva recibe el
-- suyo. Las migraciones 011 y 012 no vuelven a definir estas vistas si ya tienen la forma de
-- esta migración (CREATE OR REPLACE no admite quitar columnas).
-- Es idempotente. Replicada en db/init/01_esquema.sql.
-- ============================================================================

SET client_min_messages = warning;

CREATE OR REPLACE VIEW asistencia.v_auditoria_consulta AS
SELECT q.id_consulta, q.fecha_hora_inicio, u.nombre_usuario, q.estado, q.numero_intentos,
       q.latencia_total_ms, q.confirma_tamizaje_no_vigente, i.numero_intento, i.modelo_llm, i.tokens_entrada, i.tokens_salida,
       i.costo_usd,
       CASE WHEN i.control_identificadores THEN i.solicitud_enviada END AS solicitud_enviada,
       i.valida_citas, i.valida_consistencia, i.valida_evidencia,
       i.resultado,
       (SELECT jsonb_agg(jsonb_build_object('etiqueta', f.etiqueta_cita,
                                            'puntaje', f.puntaje_reranker,
                                            'origen', f.origen,
                                            'posicion_final', f.posicion_final,
                                            'documento', coalesce(d.codigo_documento, d.titulo),
                                            'seccion', fr.seccion,
                                            'pagina_inicio', fr.pagina_inicio,
                                            'pagina_fin', fr.pagina_fin) ORDER BY f.etiqueta_cita)
          FROM asistencia.fragmento_recuperado f
          JOIN conocimiento.fragmento fr ON fr.id_fragmento = f.id_fragmento
          JOIN conocimiento.documento_fuente d ON d.id_documento = fr.id_documento
         WHERE f.id_intento = i.id_intento AND f.enviado_al_llm) AS fragmentos_enviados,
       EXISTS (SELECT 1 FROM asistencia.intento_generacion p
                WHERE p.id_consulta = q.id_consulta AND p.modelo_llm = 'modelo-falso') AS modo_prueba,
       i.version_prompt, i.tokens_razonamiento, i.latencia_llm_ms, i.tipo_busqueda, i.candidatos_evaluados,
       i.relevancia_maxima, i.umbral_relevancia, i.control_identificadores, i.hash_solicitud,
       q.fecha_hora_fin
FROM asistencia.consulta q
JOIN seguridad.usuario u ON u.id_usuario = q.id_usuario
LEFT JOIN asistencia.intento_generacion i ON i.id_consulta = q.id_consulta;

CREATE OR REPLACE VIEW asistencia.v_auditoria_lista AS
SELECT q.id_consulta, q.fecha_hora_inicio, q.fecha_hora_fin, u.nombre_usuario, q.estado, q.numero_intentos,
       q.latencia_total_ms,
       EXISTS (SELECT 1 FROM asistencia.intento_generacion p
                WHERE p.id_consulta = q.id_consulta AND p.modelo_llm = 'modelo-falso') AS modo_prueba,
       ult.modelo_llm, ult.version_prompt, tot.tokens_entrada, tot.tokens_salida, tot.costo_usd
FROM asistencia.consulta q
JOIN seguridad.usuario u ON u.id_usuario = q.id_usuario
LEFT JOIN LATERAL (SELECT i.modelo_llm, i.version_prompt FROM asistencia.intento_generacion i
                    WHERE i.id_consulta = q.id_consulta
                    ORDER BY i.numero_intento DESC LIMIT 1) ult ON true
LEFT JOIN LATERAL (SELECT sum(i.tokens_entrada) AS tokens_entrada, sum(i.tokens_salida) AS tokens_salida,
                          sum(i.costo_usd) AS costo_usd
                     FROM asistencia.intento_generacion i WHERE i.id_consulta = q.id_consulta) tot ON true;

CREATE OR REPLACE VIEW asistencia.v_indicadores_operativos AS
WITH reales AS (
  SELECT q.* FROM asistencia.consulta q
   WHERE q.fecha_hora_inicio >= now() - interval '30 days'
     AND NOT EXISTS (SELECT 1 FROM asistencia.intento_generacion p
                      WHERE p.id_consulta = q.id_consulta AND p.modelo_llm = 'modelo-falso')
), intentos_reales AS (
  SELECT i.* FROM asistencia.intento_generacion i
   WHERE i.fecha_hora >= now() - interval '30 days'
     AND i.modelo_llm IS DISTINCT FROM 'modelo-falso'
)
SELECT count(*) AS consultas,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY latencia_total_ms)
         FILTER (WHERE numero_intentos <= 1) AS p90_flujo_normal_ms,
       round(100.0 * count(*) FILTER (WHERE numero_intentos = 2) / NULLIF(count(*), 0), 1) AS pct_con_reintento,
       round(100.0 * count(*) FILTER (WHERE estado = 'EVIDENCIA_INSUFICIENTE') / NULLIF(count(*), 0), 1) AS pct_evidencia_insuficiente,
       (SELECT coalesce(sum(costo_usd), 0) FROM intentos_reales) AS costo_api_usd,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY latencia_total_ms) AS p50_ms,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY latencia_total_ms) AS p90_ms,
       count(*) FILTER (WHERE estado IN ('VERIFICADA', 'EVIDENCIA_INSUFICIENTE')) AS evaluadas,
       count(*) FILTER (WHERE estado = 'VERIFICADA') AS verificadas,
       count(*) FILTER (WHERE estado = 'EVIDENCIA_INSUFICIENTE') AS evidencia_insuficiente,
       count(*) FILTER (WHERE estado = 'SOLICITUD_BLOQUEADA') AS solicitudes_bloqueadas,
       count(*) FILTER (WHERE estado = 'ERROR') AS errores,
       count(*) FILTER (WHERE estado = 'FUERA_DE_DOMINIO') AS fuera_de_dominio,
       count(*) FILTER (WHERE estado = 'DATOS_FALTANTES') AS datos_faltantes,
       count(*) FILTER (WHERE estado = 'TAMIZAJE_NO_VIGENTE') AS tamizaje_no_vigente,
       count(*) FILTER (WHERE estado = 'EN_PROCESO') AS en_proceso,
       count(*) FILTER (WHERE numero_intentos = 2) AS con_reintento,
       round(100.0 * count(*) FILTER (WHERE estado = 'VERIFICADA') / NULLIF(count(*), 0), 1) AS pct_verificadas,
       (SELECT coalesce(sum(tokens_entrada), 0) FROM intentos_reales) AS tokens_entrada,
       (SELECT coalesce(sum(tokens_salida), 0) FROM intentos_reales) AS tokens_salida,
       now() - interval '30 days' AS desde,
       now() AS hasta
FROM reales;

COMMENT ON VIEW asistencia.v_auditoria_consulta IS 'Detalle de auditoría por intento (M13): modelo, tokens, costo, solicitud enviada (solo si el control previo la aprobó), fragmentos con puntaje y origen, verificación y modo_prueba. Sin identidad del paciente ni texto original.';
COMMENT ON VIEW asistencia.v_auditoria_lista IS 'Una fila por consulta para la lista paginada de M13: usuario, estado, intentos, latencia, modo_prueba, modelo, tokens y costo. Sin identidad del paciente ni texto original.';
COMMENT ON VIEW asistencia.v_indicadores_operativos IS 'Indicadores de los últimos 30 días sin las consultas de prueba del cliente falso.';

GRANT SELECT ON asistencia.v_auditoria_consulta, asistencia.v_auditoria_lista,
      asistencia.v_indicadores_operativos TO rol_auditor;
