-- ============================================================================
-- CDSS Anemia Infantil · Migración 016 (Sprint 3, parte E1b: edición de parámetros M12, HU14)
-- Trigger BEFORE INSERT en umbral_hemoglobina, ajuste_altitud y parametro_sistema: para las
-- conexiones de la aplicación, una versión nueva entra vigente (vigente_hasta nulo) y con
-- vigente_desde en el día de hoy en Lima (la edición usa now(), la misma marca de tiempo con la que
-- cierra la versión anterior, así que el historial queda contiguo y exacto dentro del día). No se
-- puede insertar una versión ya cerrada ni una con fecha pasada o futura: el historial solo crece
-- hacia adelante. El propietario de la tabla o un superusuario (migraciones, carga inicial y pruebas)
-- queda exento, con el mismo criterio que fn_historial_solo_cierre (migración 015).
-- Es idempotente. Replicada en db/init/01_esquema.sql.
-- ============================================================================

SET client_min_messages = warning;

CREATE OR REPLACE FUNCTION configuracion.fn_version_nueva_vigente() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
     OR pg_has_role(current_user, (SELECT relowner FROM pg_class WHERE oid = TG_RELID), 'MEMBER') THEN
    RETURN NEW;
  END IF;
  IF NEW.vigente_hasta IS NOT NULL THEN
    RAISE EXCEPTION 'Una versión nueva de un parámetro entra vigente: no se puede insertar una versión cerrada'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.vigente_desde AT TIME ZONE 'America/Lima')::date <> (now() AT TIME ZONE 'America/Lima')::date THEN
    RAISE EXCEPTION 'Una versión nueva de un parámetro rige desde hoy: no se admite una fecha pasada ni futura'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
COMMENT ON FUNCTION configuracion.fn_version_nueva_vigente() IS 'Las versiones nuevas de los parámetros entran vigentes y desde hoy (Lima). Sin restricción para el propietario de la tabla o un superusuario.';

DROP TRIGGER IF EXISTS tg_umbral_version_nueva ON configuracion.umbral_hemoglobina;
CREATE TRIGGER tg_umbral_version_nueva BEFORE INSERT ON configuracion.umbral_hemoglobina
  FOR EACH ROW EXECUTE FUNCTION configuracion.fn_version_nueva_vigente();
DROP TRIGGER IF EXISTS tg_ajuste_version_nueva ON configuracion.ajuste_altitud;
CREATE TRIGGER tg_ajuste_version_nueva BEFORE INSERT ON configuracion.ajuste_altitud
  FOR EACH ROW EXECUTE FUNCTION configuracion.fn_version_nueva_vigente();
DROP TRIGGER IF EXISTS tg_parametro_version_nueva ON configuracion.parametro_sistema;
CREATE TRIGGER tg_parametro_version_nueva BEFORE INSERT ON configuracion.parametro_sistema
  FOR EACH ROW EXECUTE FUNCTION configuracion.fn_version_nueva_vigente();
