-- ============================================================================
-- CDSS Anemia Infantil · Migración 015 (Sprint 3, parte E1a: parámetros clínicos M12, HU14)
-- Base de M12 antes de las rutas de edición (parte E1b):
-- 1. Columnas nuevas en las tres tablas versionadas (umbral_hemoglobina, ajuste_altitud y
--    parametro_sistema): motivo_cambio, referencia (tabla y página de la norma) y verificado
--    (contrastado con la norma; falso en las filas sembradas, todas con [VERIFICAR]). En
--    parametro_sistema, id_documento (nulo permitido). categoria_anemia no se versiona: queda en
--    solo lectura (decisión 4).
-- 2. Historial cerrado: rol_app_admin solo puede cerrar una fila vigente (UPDATE de vigente_hasta)
--    e insertar versiones nuevas; no puede cambiar valores ni editar categoria_anemia. El trigger
--    fn_historial_solo_cierre admite, para cualquier otro rol, solo el cambio de vigente_hasta de
--    NULL a una fecha no anterior a vigente_desde. El propietario de la tabla o un superusuario
--    (migraciones, carga inicial y desmontaje de las pruebas) no tiene la restricción. Las
--    migraciones anteriores solo cierran filas vigentes, así que se pueden volver a aplicar.
-- 3. ex_umbral_hb_sin_traslape: en edades que se superponen, los rangos de Hb vigentes de
--    categorías distintas no se superponen (un límite nulo es abierto).
-- 4. Permisos: VER_PARAMETROS (Coordinador CRED y Administrador) para leer M12 y su historial;
--    CONFIGURAR_PARAMETROS solo para el Coordinador CRED.
-- Es idempotente. Replicada en db/init/01_esquema.sql y db/init/02_catalogos.sql.
-- ============================================================================

SET client_min_messages = warning;

-- 1. Columnas ----------------------------------------------------------------
ALTER TABLE configuracion.umbral_hemoglobina ADD COLUMN IF NOT EXISTS motivo_cambio VARCHAR(500);
ALTER TABLE configuracion.umbral_hemoglobina ADD COLUMN IF NOT EXISTS referencia VARCHAR(200);
ALTER TABLE configuracion.umbral_hemoglobina ADD COLUMN IF NOT EXISTS verificado BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE configuracion.ajuste_altitud ADD COLUMN IF NOT EXISTS motivo_cambio VARCHAR(500);
ALTER TABLE configuracion.ajuste_altitud ADD COLUMN IF NOT EXISTS referencia VARCHAR(200);
ALTER TABLE configuracion.ajuste_altitud ADD COLUMN IF NOT EXISTS verificado BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE configuracion.parametro_sistema ADD COLUMN IF NOT EXISTS motivo_cambio VARCHAR(500);
ALTER TABLE configuracion.parametro_sistema ADD COLUMN IF NOT EXISTS referencia VARCHAR(200);
ALTER TABLE configuracion.parametro_sistema ADD COLUMN IF NOT EXISTS verificado BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE configuracion.parametro_sistema ADD COLUMN IF NOT EXISTS id_documento UUID
  REFERENCES conocimiento.documento_fuente (id_documento);
CREATE INDEX IF NOT EXISTS ix_parametro_sistema_id_documento ON configuracion.parametro_sistema (id_documento);

COMMENT ON COLUMN configuracion.umbral_hemoglobina.motivo_cambio IS 'Motivo del cambio que creó esta versión (obligatorio desde M12; nulo en la carga inicial).';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.referencia IS 'Tabla y página de la norma de la que sale el valor.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.verificado IS 'Valor contrastado con el texto de la norma; falso mientras siga pendiente de verificación.';
COMMENT ON COLUMN configuracion.ajuste_altitud.motivo_cambio IS 'Motivo del cambio que creó esta versión (obligatorio desde M12; nulo en la carga inicial).';
COMMENT ON COLUMN configuracion.ajuste_altitud.referencia IS 'Tabla y página de la norma de la que sale el valor.';
COMMENT ON COLUMN configuracion.ajuste_altitud.verificado IS 'Valor contrastado con el texto de la norma; falso mientras siga pendiente de verificación.';
COMMENT ON COLUMN configuracion.parametro_sistema.motivo_cambio IS 'Motivo del cambio que creó esta versión (obligatorio desde M12; nulo en la carga inicial y en las migraciones).';
COMMENT ON COLUMN configuracion.parametro_sistema.referencia IS 'Tabla y página de la norma o medición de la que sale el valor.';
COMMENT ON COLUMN configuracion.parametro_sistema.verificado IS 'Valor contrastado con su fuente; falso mientras siga pendiente de verificación.';
COMMENT ON COLUMN configuracion.parametro_sistema.id_documento IS 'Norma de la que procede el valor, si corresponde (por ejemplo, la vigencia del tamizaje).';

-- 2. Historial cerrado -------------------------------------------------------
CREATE OR REPLACE FUNCTION configuracion.fn_historial_solo_cierre() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- El propietario de la tabla o un superusuario (migraciones, carga inicial, desmontaje de las
  -- pruebas) puede corregir el historial; las conexiones de la aplicación, no.
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
     OR pg_has_role(current_user, (SELECT relowner FROM pg_class WHERE oid = TG_RELID), 'MEMBER') THEN
    RETURN NEW;
  END IF;
  IF OLD.vigente_hasta IS NOT NULL THEN
    RAISE EXCEPTION 'El historial de parámetros no se modifica: la versión de %.% ya está cerrada', TG_TABLE_SCHEMA, TG_TABLE_NAME
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (to_jsonb(NEW) - 'vigente_hasta') IS DISTINCT FROM (to_jsonb(OLD) - 'vigente_hasta') THEN
    RAISE EXCEPTION 'El historial de parámetros no se modifica: para cambiar un valor se cierra la versión vigente y se crea otra'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.vigente_hasta IS NULL OR NEW.vigente_hasta < OLD.vigente_desde THEN
    RAISE EXCEPTION 'Una versión vigente solo se cierra con una fecha no anterior a su inicio de vigencia'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
COMMENT ON FUNCTION configuracion.fn_historial_solo_cierre() IS 'Las versiones de los parámetros solo se cierran (vigente_hasta de NULL a una fecha); los valores no se editan. Sin restricción para el propietario de la tabla o un superusuario.';

DROP TRIGGER IF EXISTS tg_umbral_solo_cierre ON configuracion.umbral_hemoglobina;
CREATE TRIGGER tg_umbral_solo_cierre BEFORE UPDATE ON configuracion.umbral_hemoglobina
  FOR EACH ROW EXECUTE FUNCTION configuracion.fn_historial_solo_cierre();
DROP TRIGGER IF EXISTS tg_ajuste_solo_cierre ON configuracion.ajuste_altitud;
CREATE TRIGGER tg_ajuste_solo_cierre BEFORE UPDATE ON configuracion.ajuste_altitud
  FOR EACH ROW EXECUTE FUNCTION configuracion.fn_historial_solo_cierre();
DROP TRIGGER IF EXISTS tg_parametro_solo_cierre ON configuracion.parametro_sistema;
CREATE TRIGGER tg_parametro_solo_cierre BEFORE UPDATE ON configuracion.parametro_sistema
  FOR EACH ROW EXECUTE FUNCTION configuracion.fn_historial_solo_cierre();

-- Revocar UPDATE de la tabla también revoca los permisos por columna: luego se concede solo
-- vigente_hasta.
REVOKE UPDATE ON configuracion.umbral_hemoglobina, configuracion.ajuste_altitud, configuracion.parametro_sistema
  FROM rol_app_admin;
GRANT UPDATE (vigente_hasta) ON configuracion.umbral_hemoglobina, configuracion.ajuste_altitud,
  configuracion.parametro_sistema TO rol_app_admin;
REVOKE INSERT, UPDATE ON configuracion.categoria_anemia FROM rol_app_admin;

-- 3. Rangos de Hb sin traslape entre categorías ------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ex_umbral_hb_sin_traslape') THEN
    ALTER TABLE configuracion.umbral_hemoglobina ADD CONSTRAINT ex_umbral_hb_sin_traslape
      EXCLUDE USING gist (int4range(edad_min_meses, edad_max_meses, '[]') WITH &&,
                          numrange(hb_min_g_dl, hb_max_g_dl, '[]') WITH &&)
      WHERE (vigente_hasta IS NULL);
  END IF;
END $$;

-- 4. Permisos de aplicación --------------------------------------------------
INSERT INTO seguridad.permiso (codigo, descripcion) VALUES
  ('VER_PARAMETROS', 'Consultar los parámetros clínicos y del sistema y su historial')
ON CONFLICT (codigo) DO NOTHING;
UPDATE seguridad.permiso SET descripcion = 'Modificar los puntos de corte, el ajuste por altitud y la vigencia del tamizaje'
 WHERE codigo = 'CONFIGURAR_PARAMETROS';
INSERT INTO seguridad.rol_permiso (id_rol, id_permiso)
SELECT r.id_rol, p.id_permiso
  FROM seguridad.rol r JOIN seguridad.permiso p ON p.codigo = 'VER_PARAMETROS'
 WHERE r.nombre IN ('Coordinador CRED', 'Administrador')
ON CONFLICT DO NOTHING;
DELETE FROM seguridad.rol_permiso rp
 USING seguridad.rol r, seguridad.permiso p
 WHERE rp.id_rol = r.id_rol AND rp.id_permiso = p.id_permiso
   AND r.nombre = 'Administrador' AND p.codigo = 'CONFIGURAR_PARAMETROS';
