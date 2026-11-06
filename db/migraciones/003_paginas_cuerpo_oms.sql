-- ============================================================================
-- CDSS Anemia Infantil · Migración 003 (Sprint 2: páginas del cuerpo de las guías OMS)
-- Se indexa solo el cuerpo de cada guía, sin resumen ejecutivo, referencias ni
-- anexos: OMS 2024, págs. 22 a 55 (Background a Management of competing
-- interests); OMS 2016, págs. 13 a 28 (Scope and purpose a la declaración de
-- intereses). Solo completa los valores que siguen vacíos: es idempotente y no
-- pisa un cambio hecho después.
-- ============================================================================

SET client_min_messages = warning;

UPDATE conocimiento.documento_fuente
   SET pagina_inicio_cuerpo = 22, pagina_fin_cuerpo = 55
 WHERE id_documento = '10000000-0000-0000-0000-000000002024'
   AND pagina_inicio_cuerpo IS NULL AND pagina_fin_cuerpo IS NULL;

UPDATE conocimiento.documento_fuente
   SET pagina_inicio_cuerpo = 13, pagina_fin_cuerpo = 28
 WHERE id_documento = '10000000-0000-0000-0000-000000002016'
   AND pagina_inicio_cuerpo IS NULL AND pagina_fin_cuerpo IS NULL;
