-- ============================================================================
-- CDSS Anemia Infantil · Usuarios de conexión del backend (mínimo privilegio)
-- Cada componente del backend se conecta con su propio usuario, que hereda
-- los permisos de un rol definido en 01_esquema.sql:
--   cdss_clinica    -> rol_app_clinica    (pacientes, tamizajes, re-vinculación, autenticación)
--   cdss_generacion -> rol_app_generacion (recuperación, solicitud mínima, verificación)
--   cdss_admin      -> rol_app_admin      (usuarios, guías, parámetros)
--   cdss_auditor    -> rol_auditor        (solo lectura de auditoría)
-- Las contraseñas se reciben como variables de configuración de la sesión
-- (cdss.pwd_*), que fijan db/init/03_usuarios_bd.sh (Docker) o db/aplicar_bd.sh (Azure).
-- ============================================================================

-- La autenticación (HU01) necesita leer cuentas, roles y permisos, y
-- actualizar solo los campos de control de acceso de la cuenta.
GRANT SELECT ON seguridad.usuario, seguridad.rol, seguridad.permiso, seguridad.rol_permiso TO rol_app_clinica;
GRANT UPDATE (intentos_fallidos, ultimo_acceso) ON seguridad.usuario TO rol_app_clinica;

DO $$
DECLARE
  par record;
BEGIN
  FOR par IN
    SELECT * FROM (VALUES
      ('cdss_clinica',    'rol_app_clinica',    current_setting('cdss.pwd_clinica', true)),
      ('cdss_generacion', 'rol_app_generacion', current_setting('cdss.pwd_generacion', true)),
      ('cdss_admin',      'rol_app_admin',      current_setting('cdss.pwd_admin', true)),
      ('cdss_auditor',    'rol_auditor',        current_setting('cdss.pwd_auditor', true))
    ) AS t(usuario, rol, pwd)
  LOOP
    IF par.pwd IS NULL OR par.pwd = '' THEN
      RAISE EXCEPTION 'Falta la contraseña para %, defina cdss.pwd_* antes de ejecutar el script', par.usuario;
    END IF;
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = par.usuario) THEN
        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L IN ROLE %I', par.usuario, par.pwd, par.rol);
      ELSE
        EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', par.usuario, par.pwd);
      END IF;
    EXCEPTION WHEN OTHERS THEN
      -- No se propaga el error original: su contexto incluye la sentencia con la contraseña
      RAISE EXCEPTION 'No se pudo crear o actualizar el usuario % (código de error %)', par.usuario, SQLSTATE;
    END;
  END LOOP;
END $$;
