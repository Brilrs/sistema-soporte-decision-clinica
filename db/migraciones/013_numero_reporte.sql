-- ============================================================================
-- CDSS Anemia Infantil · Migración 013 (Sprint 3, parte C1: reporte exportable M09, HU10)
-- Número correlativo del reporte (asistencia.reporte.numero_reporte), con el formato
-- EV-AAAA-NNNNN: AAAA es el año de emisión en hora de Perú y NNNNN, el valor de una secuencia
-- global con al menos 5 cifras (más si hace falta, sin truncar).
-- Se eligió una secuencia global con el prefijo del año, y no un contador por año, porque nextval
-- es atómico y no bloquea entre transacciones: dos reportes simultáneos nunca repiten número y no
-- hace falta una tabla de contadores con bloqueo de fila. El número sigue creciendo al cambiar de
-- año (no vuelve a 00001); los huecos por una transacción revertida son aceptables.
-- La función asistencia.siguiente_numero_reporte() reserva el número y devuelve también la fecha
-- y hora de emisión de la base, para no depender del reloj del servidor de la aplicación.
-- Las columnas de asistencia.reporte ya alcanzan (número único, destino, secciones, formato, hash,
-- usuario y fecha). Permiso: solo rol_app_clinica usa la secuencia y la función.
-- Es idempotente. Replicada en db/init/01_esquema.sql.
-- ============================================================================

SET client_min_messages = warning;

CREATE SEQUENCE IF NOT EXISTS asistencia.reporte_numero_seq AS bigint START WITH 1 MINVALUE 1 NO CYCLE;
COMMENT ON SEQUENCE asistencia.reporte_numero_seq IS 'Correlativo global de asistencia.reporte.numero_reporte (EV-AAAA-NNNNN). Puede tener huecos por transacciones revertidas.';

CREATE OR REPLACE FUNCTION asistencia.siguiente_numero_reporte(OUT numero_reporte varchar, OUT fecha_emision timestamptz)
LANGUAGE sql VOLATILE AS $$
  WITH n AS (SELECT nextval('asistencia.reporte_numero_seq') AS v, now() AS f)
  SELECT 'EV-' || to_char(n.f AT TIME ZONE 'America/Lima', 'YYYY') || '-' ||
         lpad(n.v::text, greatest(5, length(n.v::text)), '0'),
         n.f
    FROM n;
$$;
COMMENT ON FUNCTION asistencia.siguiente_numero_reporte() IS 'Reserva el siguiente número de reporte (EV-AAAA-NNNNN, año en hora de Perú) y devuelve la fecha y hora de emisión.';

REVOKE ALL ON SEQUENCE asistencia.reporte_numero_seq FROM PUBLIC;
REVOKE ALL ON FUNCTION asistencia.siguiente_numero_reporte() FROM PUBLIC;
REVOKE ALL ON SEQUENCE asistencia.reporte_numero_seq FROM rol_app_generacion, rol_app_admin;
GRANT USAGE ON SEQUENCE asistencia.reporte_numero_seq TO rol_app_clinica;
GRANT EXECUTE ON FUNCTION asistencia.siguiente_numero_reporte() TO rol_app_clinica;
