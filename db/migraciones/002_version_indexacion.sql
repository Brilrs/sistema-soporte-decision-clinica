-- ============================================================================
-- CDSS Anemia Infantil · Migración 002 (Sprint 2: versión de indexación)
-- Permite reindexar un documento sin eliminar fragmentos: cada indexación crea
-- una versión nueva y los fragmentos de las versiones anteriores pasan a no
-- vigentes. Es idempotente y sobre una base nueva no cambia nada.
-- ============================================================================

SET client_min_messages = warning;

ALTER TABLE conocimiento.fragmento
  ADD COLUMN IF NOT EXISTS version_indexacion SMALLINT NOT NULL DEFAULT 1;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fragmento_id_documento_numero_orden_key') THEN
    ALTER TABLE conocimiento.fragmento DROP CONSTRAINT fragmento_id_documento_numero_orden_key;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_fragmento_documento_version_orden') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT uq_fragmento_documento_version_orden
      UNIQUE (id_documento, version_indexacion, numero_orden);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_fragmento_version_indexacion') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT ck_fragmento_version_indexacion
      CHECK (version_indexacion >= 1);
  END IF;
END $$;

COMMENT ON COLUMN conocimiento.fragmento.version_indexacion IS 'Número de la indexación del documento que generó el fragmento. Al reindexar, los fragmentos de las versiones anteriores pasan a no vigentes y solo los de la última versión están en ChromaDB.';
