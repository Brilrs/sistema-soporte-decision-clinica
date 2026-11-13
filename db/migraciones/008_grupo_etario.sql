-- ============================================================================
-- CDSS Anemia Infantil · Migración 008 (Sprint 2, parte C2: recuperación con edad)
-- Grupo etario de cada fragmento (edad mínima y máxima en meses y población), que el
-- indexador asigna desde los títulos de la sección o el texto (grupos_etarios.py), y
-- el parámetro BONIFICACION_EDAD de la fusión: sube los fragmentos cuyo rango incluye
-- la edad del paciente y baja los que la excluyen. Se registra en 0 (sin efecto)
-- hasta calibrarlo con el conjunto de desarrollo.
-- Es idempotente. Replicada en db/init/01_esquema.sql (columnas) y al final de
-- db/init/02_catalogos.sql (parámetro).
-- ============================================================================

SET client_min_messages = warning;

ALTER TABLE conocimiento.fragmento
  ADD COLUMN IF NOT EXISTS edad_min_meses SMALLINT,
  ADD COLUMN IF NOT EXISTS edad_max_meses SMALLINT,
  ADD COLUMN IF NOT EXISTS poblacion VARCHAR(20) NOT NULL DEFAULT 'GENERAL',
  ADD COLUMN IF NOT EXISTS origen_rango VARCHAR(10) NOT NULL DEFAULT 'TITULO',
  ADD COLUMN IF NOT EXISTS rango_dudoso BOOLEAN NOT NULL DEFAULT false;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_fragmento_poblacion') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT ck_fragmento_poblacion
      CHECK (poblacion IN ('NINO','ADOLESCENTE','GESTANTE','MUJER_EDAD_FERTIL','GENERAL'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_fragmento_origen_rango') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT ck_fragmento_origen_rango
      CHECK (origen_rango IN ('TITULO','TEXTO','MANUAL'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_fragmento_rango_edad') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT ck_fragmento_rango_edad
      CHECK (edad_min_meses IS NULL OR edad_max_meses IS NULL OR edad_min_meses <= edad_max_meses);
  END IF;
END $$;

COMMENT ON COLUMN conocimiento.fragmento.edad_min_meses IS 'Edad mínima en meses a la que aplica el fragmento; nulo sin límite.';
COMMENT ON COLUMN conocimiento.fragmento.edad_max_meses IS 'Edad máxima en meses a la que aplica el fragmento; nulo sin límite.';
COMMENT ON COLUMN conocimiento.fragmento.poblacion IS 'NINO, ADOLESCENTE, GESTANTE (incluye la puérpera), MUJER_EDAD_FERTIL o GENERAL (aplica a todos).';
COMMENT ON COLUMN conocimiento.fragmento.origen_rango IS 'De dónde salió el grupo etario: TITULO de la sección, TEXTO del fragmento o corrección MANUAL.';
COMMENT ON COLUMN conocimiento.fragmento.rango_dudoso IS 'El grupo etario mezcla varios rangos o poblaciones y queda para revisión.';

INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, modificado_por)
SELECT 'BONIFICACION_EDAD', '0', 'DECIMAL', 0, 1,
       'Peso de la edad del paciente en la fusión RRF: multiplica por (1 + peso) el puntaje de los fragmentos cuyo rango incluye la edad y por (1 - peso) el de los que la excluyen',
       '00000000-0000-0000-0000-000000000001'
WHERE NOT EXISTS (SELECT 1 FROM configuracion.parametro_sistema
                   WHERE clave = 'BONIFICACION_EDAD' AND vigente_hasta IS NULL);
