-- ============================================================================
-- CDSS Anemia Infantil · Migración 018 (Sprint 3, parte I: cambio de contraseña y sesiones)
-- Tres columnas nuevas en seguridad.usuario:
--   debe_cambiar_contrasena: marca que obliga a cambiar la contraseña antes de usar el sistema
--     (la ponen la creación de la cuenta y el restablecimiento; las cuentas ya existentes quedan en falso).
--   version_sesion: contador de sesiones. El token JWT lleva su valor (campo sv; un token sin sv cuenta
--     como 0) y solo es válido si coincide con el de la cuenta. Cambiar la contraseña, restablecerla y
--     reactivar la cuenta lo suben, de modo que las sesiones abiertas antes dejan de valer.
--   fecha_cambio_contrasena: fecha y hora del último cambio hecho por el propio usuario.
-- Permisos: el componente clínico (rol_app_clinica), que atiende el inicio de sesión y el cambio de la
-- propia contraseña, recibe UPDATE solo sobre las columnas que usa. rol_app_admin ya tiene permisos
-- sobre toda la tabla (incluidas las columnas nuevas); rol_auditor, rol_app_generacion y
-- rol_app_indexador no tienen ningún permiso sobre seguridad.usuario y no se les agrega ninguno.
-- Es idempotente. Replicada en db/init/01_esquema.sql y db/sql/usuarios_bd.sql.
-- ============================================================================

SET client_min_messages = warning;

ALTER TABLE seguridad.usuario ADD COLUMN IF NOT EXISTS debe_cambiar_contrasena BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE seguridad.usuario ADD COLUMN IF NOT EXISTS version_sesion INTEGER NOT NULL DEFAULT 0;
ALTER TABLE seguridad.usuario ADD COLUMN IF NOT EXISTS fecha_cambio_contrasena TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'ck_usuario_version_sesion'
                    AND conrelid = 'seguridad.usuario'::regclass) THEN
    ALTER TABLE seguridad.usuario ADD CONSTRAINT ck_usuario_version_sesion CHECK (version_sesion >= 0);
  END IF;
END $$;

COMMENT ON COLUMN seguridad.usuario.debe_cambiar_contrasena IS 'Verdadero si el usuario debe cambiar su contraseña antes de usar el sistema (cuenta nueva o contraseña restablecida).';
COMMENT ON COLUMN seguridad.usuario.version_sesion IS 'Contador de sesiones: un token solo es válido si lleva este mismo valor. Sube al cambiar o restablecer la contraseña y al reactivar la cuenta.';
COMMENT ON COLUMN seguridad.usuario.fecha_cambio_contrasena IS 'Fecha y hora en que el propio usuario cambió su contraseña por última vez.';

GRANT UPDATE (intentos_fallidos, ultimo_acceso, hash_contrasena, debe_cambiar_contrasena, version_sesion,
              fecha_cambio_contrasena) ON seguridad.usuario TO rol_app_clinica;
