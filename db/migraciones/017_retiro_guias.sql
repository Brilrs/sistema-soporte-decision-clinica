-- ============================================================================
-- CDSS Anemia Infantil · Migración 017 (Sprint 3, parte F: retiro de guías, HU17)
-- Coherencia del retiro en conocimiento.documento_fuente: una guía OBSOLETA tiene siempre quién la
-- retiró, cuándo y por qué (motivo de 10 a 250 caracteres sin contar espacios de los extremos), y una
-- guía VIGENTE no tiene ninguno de esos datos. Sin esta restricción, una actualización parcial (o un
-- arreglo manual) podría dejar una guía retirada sin trazabilidad, que es lo que justifica conservarla.
-- Antes de agregarla se comprueba que ninguna fila la incumpla, con un mensaje claro.
-- Es idempotente. Replicada en db/init/01_esquema.sql.
-- ============================================================================

SET client_min_messages = warning;

DO $$
DECLARE
  incoherentes integer;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'ck_documento_fuente_retiro'
                    AND conrelid = 'conocimiento.documento_fuente'::regclass) THEN
    SELECT count(*) INTO incoherentes
      FROM conocimiento.documento_fuente
     WHERE NOT ((estado = 'VIGENTE' AND retirado_por IS NULL AND fecha_retiro IS NULL AND motivo_retiro IS NULL)
             OR (estado = 'OBSOLETA' AND retirado_por IS NOT NULL AND fecha_retiro IS NOT NULL
                 AND length(btrim(motivo_retiro)) BETWEEN 10 AND 250));
    IF incoherentes > 0 THEN
      RAISE EXCEPTION 'Migración 017: % guías tienen el estado y los datos de retiro incoherentes; corríjalas antes de aplicarla', incoherentes;
    END IF;
    ALTER TABLE conocimiento.documento_fuente ADD CONSTRAINT ck_documento_fuente_retiro
      CHECK ((estado = 'VIGENTE' AND retirado_por IS NULL AND fecha_retiro IS NULL AND motivo_retiro IS NULL)
          OR (estado = 'OBSOLETA' AND retirado_por IS NOT NULL AND fecha_retiro IS NOT NULL
              AND length(btrim(motivo_retiro)) BETWEEN 10 AND 250));
  END IF;
END $$;

COMMENT ON CONSTRAINT ck_documento_fuente_retiro ON conocimiento.documento_fuente IS
  'Una guía OBSOLETA tiene quién la retiró, cuándo y el motivo (10 a 250 caracteres); una VIGENTE no tiene datos de retiro.';
