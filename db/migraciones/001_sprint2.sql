-- ============================================================================
-- CDSS Anemia Infantil · Migración 001 (Sprint 2: base de conocimiento y RAG)
-- Lleva una base creada con el esquema del Sprint 1 al mismo estado que
-- db/init/01_esquema.sql y db/init/02_catalogos.sql. Es idempotente: puede
-- aplicarse varias veces y sobre una base nueva no cambia nada.
-- Se ejecuta con db/aplicar_bd.sh (o con psql --single-transaction).
-- ============================================================================

SET client_min_messages = warning;

-- ---------------------------------------------------------------------------
-- conocimiento.documento_fuente
-- ---------------------------------------------------------------------------
ALTER TABLE conocimiento.documento_fuente
  ADD COLUMN IF NOT EXISTS fecha_publicacion DATE,
  ADD COLUMN IF NOT EXISTS idioma CHAR(2) NOT NULL DEFAULT 'es'
    CONSTRAINT ck_documento_fuente_idioma CHECK (idioma IN ('es','en')),
  ADD COLUMN IF NOT EXISTS pagina_inicio_cuerpo SMALLINT,
  ADD COLUMN IF NOT EXISTS pagina_fin_cuerpo SMALLINT,
  ALTER COLUMN ruta_blob DROP NOT NULL,
  ALTER COLUMN hash_archivo DROP NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documento_fuente_fecha_publicacion') THEN
    ALTER TABLE conocimiento.documento_fuente ADD CONSTRAINT ck_documento_fuente_fecha_publicacion
      CHECK (fecha_publicacion IS NULL OR extract(year FROM fecha_publicacion) = anio_publicacion);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documento_fuente_paginas_cuerpo') THEN
    ALTER TABLE conocimiento.documento_fuente ADD CONSTRAINT ck_documento_fuente_paginas_cuerpo
      CHECK ((pagina_inicio_cuerpo IS NULL AND pagina_fin_cuerpo IS NULL)
          OR (pagina_inicio_cuerpo >= 1 AND pagina_inicio_cuerpo <= pagina_fin_cuerpo));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_documento_fuente_archivo_indexado') THEN
    ALTER TABLE conocimiento.documento_fuente ADD CONSTRAINT ck_documento_fuente_archivo_indexado
      CHECK (estado_indexacion <> 'COMPLETADA' OR (ruta_blob IS NOT NULL AND hash_archivo IS NOT NULL));
  END IF;
END $$;

COMMENT ON COLUMN conocimiento.documento_fuente.fecha_publicacion IS 'Fecha de publicación o aprobación oficial del documento, cuando se conoce.';
COMMENT ON COLUMN conocimiento.documento_fuente.idioma IS 'Idioma del texto del documento (es o en); orienta la búsqueda léxica.';
COMMENT ON COLUMN conocimiento.documento_fuente.pagina_inicio_cuerpo IS 'Primera página del PDF que se indexa (excluye la resolución de aprobación).';
COMMENT ON COLUMN conocimiento.documento_fuente.pagina_fin_cuerpo IS 'Última página del PDF que se indexa.';
COMMENT ON COLUMN conocimiento.documento_fuente.ruta_blob IS 'Ubicación del PDF original en Azure Blob Storage; nula hasta que se carga el archivo.';
COMMENT ON COLUMN conocimiento.documento_fuente.hash_archivo IS 'SHA-256 del archivo, para evitar cargas duplicadas; nulo hasta que se carga el archivo.';

-- ---------------------------------------------------------------------------
-- conocimiento.fragmento
-- ---------------------------------------------------------------------------
ALTER TABLE conocimiento.fragmento
  ADD COLUMN IF NOT EXISTS vigente BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS id_documento_modificatorio UUID REFERENCES conocimiento.documento_fuente (id_documento),
  ADD COLUMN IF NOT EXISTS motivo_exclusion VARCHAR(250),
  ADD COLUMN IF NOT EXISTS tipo_contenido VARCHAR(10) NOT NULL DEFAULT 'TEXTO'
    CONSTRAINT ck_fragmento_tipo_contenido CHECK (tipo_contenido IN ('TEXTO','TABLA')),
  ADD COLUMN IF NOT EXISTS fuente_texto VARCHAR(15) NOT NULL DEFAULT 'CAPA_TEXTO'
    CONSTRAINT ck_fragmento_fuente_texto CHECK (fuente_texto IN ('CAPA_TEXTO','OCR','TRANSCRIPCION')),
  ADD COLUMN IF NOT EXISTS verificado BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS fecha_verificacion TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_fragmento_motivo_exclusion') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT ck_fragmento_motivo_exclusion
      CHECK (vigente OR motivo_exclusion IS NOT NULL);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_fragmento_verificacion') THEN
    ALTER TABLE conocimiento.fragmento ADD CONSTRAINT ck_fragmento_verificacion
      CHECK (verificado = (fecha_verificacion IS NOT NULL));
  END IF;
END $$;

COMMENT ON COLUMN conocimiento.fragmento.vigente IS 'Falso cuando el texto fue sustituido por un documento modificatorio; el fragmento se conserva para la trazabilidad pero no se recupera.';
COMMENT ON COLUMN conocimiento.fragmento.id_documento_modificatorio IS 'Documento que sustituye el texto de este fragmento (p. ej., la RM 429-2024/MINSA).';
COMMENT ON COLUMN conocimiento.fragmento.motivo_exclusion IS 'Motivo por el que el fragmento no es vigente; obligatorio cuando vigente es falso.';
COMMENT ON COLUMN conocimiento.fragmento.tipo_contenido IS 'TEXTO o TABLA; las tablas se conservan completas en un solo fragmento.';
COMMENT ON COLUMN conocimiento.fragmento.fuente_texto IS 'Origen del texto: CAPA_TEXTO del PDF, OCR o TRANSCRIPCION manual.';
COMMENT ON COLUMN conocimiento.fragmento.verificado IS 'Indica que el texto fue contrastado con la imagen del documento original.';
COMMENT ON COLUMN conocimiento.fragmento.fecha_verificacion IS 'Fecha y hora de la verificación; obligatoria si verificado es verdadero.';
CREATE INDEX IF NOT EXISTS ix_fragmento_id_documento_modificatorio ON conocimiento.fragmento (id_documento_modificatorio);

-- ---------------------------------------------------------------------------
-- conocimiento.trabajo_indexacion
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conocimiento.trabajo_indexacion (
  id_trabajo UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_documento UUID NOT NULL REFERENCES conocimiento.documento_fuente (id_documento),
  tipo VARCHAR(12) NOT NULL CONSTRAINT ck_trabajo_indexacion_tipo CHECK (tipo IN ('INDEXACION','REINDEXACION','RETIRO')),
  estado VARCHAR(10) NOT NULL DEFAULT 'PENDIENTE' CONSTRAINT ck_trabajo_indexacion_estado CHECK (estado IN ('PENDIENTE','EN_CURSO','COMPLETADO','ERROR')),
  etapa VARCHAR(15) CONSTRAINT ck_trabajo_indexacion_etapa CHECK (etapa IN ('EXTRACCION','FRAGMENTACION','NORMALIZACION','EMBEDDINGS','INDEXACION')),
  procesados INTEGER NOT NULL DEFAULT 0 CHECK (procesados >= 0),
  total INTEGER CHECK (total >= 0),
  mensaje_error VARCHAR(500),
  solicitado_por UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),
  fecha_inicio TIMESTAMPTZ,
  fecha_fin TIMESTAMPTZ,
  CONSTRAINT ck_trabajo_indexacion_avance CHECK (total IS NULL OR procesados <= total),
  CONSTRAINT ck_trabajo_indexacion_error CHECK (estado <> 'ERROR' OR mensaje_error IS NOT NULL)
);
COMMENT ON TABLE conocimiento.trabajo_indexacion IS 'Cola y avance de los trabajos del pipeline de indexación. El contenedor Jobs toma los trabajos pendientes y la pantalla de base de conocimiento (M11) lee aquí la etapa y el número de fragmentos procesados.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.id_trabajo IS 'Identificador del trabajo.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.id_documento IS 'Documento que se procesa.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.tipo IS 'INDEXACION, REINDEXACION o RETIRO.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.estado IS 'PENDIENTE, EN_CURSO, COMPLETADO o ERROR.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.etapa IS 'Etapa en curso: EXTRACCION, FRAGMENTACION, NORMALIZACION, EMBEDDINGS o INDEXACION.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.procesados IS 'Fragmentos procesados en la etapa en curso.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.total IS 'Total de fragmentos de la etapa en curso, cuando ya se conoce.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.mensaje_error IS 'Descripción del error; obligatoria si el estado es ERROR.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.solicitado_por IS 'Usuario que solicitó el trabajo.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.fecha_solicitud IS 'Fecha y hora de la solicitud.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.fecha_inicio IS 'Inicio del procesamiento.';
COMMENT ON COLUMN conocimiento.trabajo_indexacion.fecha_fin IS 'Fin del procesamiento.';
CREATE INDEX IF NOT EXISTS ix_trabajo_indexacion_id_documento ON conocimiento.trabajo_indexacion (id_documento);
CREATE INDEX IF NOT EXISTS ix_trabajo_indexacion_solicitado_por ON conocimiento.trabajo_indexacion (solicitado_por);
CREATE INDEX IF NOT EXISTS ix_trabajo_indexacion_estado ON conocimiento.trabajo_indexacion (estado, fecha_solicitud);

-- ---------------------------------------------------------------------------
-- asistencia.consulta, asistencia.intento_generacion y asistencia.cita_evidencia
-- ---------------------------------------------------------------------------
ALTER TABLE asistencia.consulta
  ADD COLUMN IF NOT EXISTS texto_filtrado TEXT,
  ADD COLUMN IF NOT EXISTS idioma_respuesta CHAR(2) NOT NULL DEFAULT 'es'
    CONSTRAINT ck_consulta_idioma_respuesta CHECK (idioma_respuesta IN ('es','en'));
COMMENT ON COLUMN asistencia.consulta.texto_filtrado IS 'Texto de la consulta tras el filtro de texto libre (4.4), sin identificadores; es el único texto de la consulta que lee el componente de generación.';
COMMENT ON COLUMN asistencia.consulta.idioma_respuesta IS 'Idioma en que se genera la recomendación (es o en).';

COMMENT ON TABLE asistencia.intento_generacion IS 'Cada ejecución del ciclo de recuperación, protección, generación y verificación de una consulta. El primer intento corresponde a la búsqueda inicial y el segundo, al único reintento permitido. Registra la solicitud desidentificada efectivamente enviada al proveedor, el consumo de tokens, el costo y el resultado de cada verificación en línea.';

ALTER TABLE asistencia.cita_evidencia ADD COLUMN IF NOT EXISTS extracto_traducido TEXT;
COMMENT ON COLUMN asistencia.cita_evidencia.extracto_traducido IS 'Traducción de apoyo al español del extracto cuando la guía está en otro idioma; no oficial.';

-- ---------------------------------------------------------------------------
-- Roles y permisos (mínimo privilegio)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rol_app_indexador') THEN
    CREATE ROLE rol_app_indexador NOLOGIN;
  END IF;
END $$;

REVOKE ALL ON conocimiento.trabajo_indexacion FROM rol_app_clinica;

-- El componente de generación no puede leer la identidad del paciente ni el texto
-- libre sin filtrar: de la consulta lee todo salvo texto_consulta y del tamizaje
-- todo salvo observaciones (permisos por columna).
REVOKE SELECT, UPDATE ON asistencia.consulta FROM rol_app_generacion;
REVOKE SELECT ON clinico.tamizaje FROM rol_app_generacion;
GRANT SELECT ON clinico.paciente, clinico.tamizaje_sintoma, clinico.sintoma,
      clinico.resultado_clasificacion, asistencia.v_historial_hemoglobina TO rol_app_generacion;
GRANT SELECT (id_tamizaje, id_paciente, id_usuario, fecha_tamizaje, edad_meses, hemoglobina_g_dl,
              metodo_medicion, peso_kg, talla_cm, recibe_suplementacion_hierro,
              lactancia_materna_actual, parasitosis_reciente, fecha_registro)
  ON clinico.tamizaje TO rol_app_generacion;
GRANT SELECT (id_consulta, id_consulta_previa, id_tamizaje, id_usuario, texto_filtrado, estado,
              numero_intentos, fecha_hora_inicio, fecha_hora_fin, latencia_total_ms,
              confirma_tamizaje_no_vigente, idioma_respuesta)
  ON asistencia.consulta TO rol_app_generacion;
GRANT UPDATE (estado, numero_intentos, fecha_hora_fin, latencia_total_ms)
  ON asistencia.consulta TO rol_app_generacion;
GRANT SELECT ON ALL TABLES IN SCHEMA conocimiento, configuracion TO rol_app_generacion;
REVOKE ALL ON conocimiento.trabajo_indexacion FROM rol_app_generacion;
REVOKE ALL ON clinico.paciente_identidad FROM rol_app_generacion;

GRANT SELECT, INSERT, UPDATE ON conocimiento.trabajo_indexacion TO rol_app_admin;

-- El indexador solo trabaja con la base de conocimiento: sin acceso a datos
-- clínicos ni a cuentas, y sin permiso de eliminación.
REVOKE ALL ON SCHEMA seguridad, clinico, asistencia FROM rol_app_indexador;
GRANT USAGE ON SCHEMA conocimiento, configuracion, auditoria TO rol_app_indexador;
GRANT SELECT ON ALL TABLES IN SCHEMA conocimiento TO rol_app_indexador;
GRANT SELECT ON configuracion.parametro_sistema TO rol_app_indexador;
GRANT INSERT, UPDATE ON conocimiento.fragmento, conocimiento.trabajo_indexacion TO rol_app_indexador;
GRANT UPDATE (ruta_blob, hash_archivo, estado_indexacion, total_fragmentos)
  ON conocimiento.documento_fuente TO rol_app_indexador;
GRANT INSERT ON auditoria.evento_auditoria TO rol_app_indexador;
GRANT USAGE ON SEQUENCE auditoria.evento_auditoria_id_evento_seq TO rol_app_indexador;

-- ---------------------------------------------------------------------------
-- Documentos fuente: NTS 213 aprobada por la RM 251-2024/MINSA (08/04/2024)
-- y modificada por la RM 429-2024/MINSA (18/06/2024)
-- ---------------------------------------------------------------------------
UPDATE conocimiento.documento_fuente SET ruta_blob = NULL, hash_archivo = NULL
 WHERE left(ruta_blob, 12) = 'pendiente://' AND estado_indexacion <> 'COMPLETADA';

UPDATE conocimiento.documento_fuente
   SET fecha_publicacion = DATE '2024-04-08', version = coalesce(version, 'RM 251-2024/MINSA'),
       idioma = 'es', pagina_inicio_cuerpo = 4, pagina_fin_cuerpo = 36
 WHERE id_documento = '10000000-0000-0000-0000-000000000213' AND fecha_publicacion IS NULL;

UPDATE conocimiento.documento_fuente SET idioma = 'en'
 WHERE id_documento IN ('10000000-0000-0000-0000-000000002024', '10000000-0000-0000-0000-000000002016')
   AND idioma <> 'en';

INSERT INTO conocimiento.documento_fuente
  (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
   fecha_publicacion, version, idioma, pagina_inicio_cuerpo, pagina_fin_cuerpo, cargado_por)
VALUES
  ('10000000-0000-0000-0000-000000000429',
   'NTS 213-MINSA/DGIESP-2024 modificada por RM 429-2024/MINSA', 'RM 429-2024/MINSA',
   'MINSA', 'RESOLUCION', 1, 2024, DATE '2024-06-18', 'RM 429-2024/MINSA', 'es', 4, 11,
   '00000000-0000-0000-0000-000000000001')
ON CONFLICT (id_documento) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Ajuste por altitud: el rango 4500 a 5500 se divide según la Tabla 1 del
-- Anexo de la RM 429-2024/MINSA. La fila anterior se cierra, no se borra.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  UPDATE configuracion.ajuste_altitud SET vigente_hasta = now()
   WHERE altitud_min_msnm = 4500 AND altitud_max_msnm = 5500 AND vigente_hasta IS NULL;
  IF NOT EXISTS (SELECT 1 FROM configuracion.ajuste_altitud
                  WHERE altitud_min_msnm = 4500 AND altitud_max_msnm = 4999 AND vigente_hasta IS NULL) THEN
    INSERT INTO configuracion.ajuste_altitud
      (id_documento, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, modificado_por)
    VALUES ('10000000-0000-0000-0000-000000000429', 4500, 4999, 3.3, '00000000-0000-0000-0000-000000000001');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM configuracion.ajuste_altitud
                  WHERE altitud_min_msnm = 5000 AND altitud_max_msnm = 5500 AND vigente_hasta IS NULL) THEN
    INSERT INTO configuracion.ajuste_altitud
      (id_documento, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, modificado_por)
    VALUES ('10000000-0000-0000-0000-000000000429', 5000, 5500, 4.0, '00000000-0000-0000-0000-000000000001');
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Parámetros del sistema (se versionan: se cierra el valor y se crea otro)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM configuracion.parametro_sistema
              WHERE clave = 'MODELO_LLM' AND valor = 'claude-sonnet-4-5' AND vigente_hasta IS NULL)
     OR NOT EXISTS (SELECT 1 FROM configuracion.parametro_sistema
                     WHERE clave = 'MODELO_LLM' AND vigente_hasta IS NULL) THEN
    UPDATE configuracion.parametro_sistema SET vigente_hasta = now()
     WHERE clave = 'MODELO_LLM' AND vigente_hasta IS NULL;
    INSERT INTO configuracion.parametro_sistema (clave, valor, tipo_dato, descripcion, modificado_por)
    VALUES ('MODELO_LLM', 'claude-sonnet-5-5', 'TEXTO', 'Identificador del modelo de lenguaje',
            '00000000-0000-0000-0000-000000000001');
  END IF;
END $$;

-- El modelo vigente no admite el parámetro de temperatura: el valor se cierra
-- y se conserva en el historial.
UPDATE configuracion.parametro_sistema SET vigente_hasta = now()
 WHERE clave = 'TEMPERATURA_LLM' AND vigente_hasta IS NULL;

INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, modificado_por)
SELECT v.clave, v.valor, v.tipo, v.vmin, v.vmax, v.descr, '00000000-0000-0000-0000-000000000001'
FROM (VALUES
  ('UMBRAL_DOMINIO',           '0.50', 'DECIMAL', 0, 1,    'Similitud mínima con las consultas de referencia del dominio (valor provisional, se calibra con las pruebas de recuperación)'),
  ('PRECIO_ENTRADA_USD_MTOK',  '2.00', 'DECIMAL', 0, 1000, 'Precio en dólares por millón de tokens de entrada del modelo de lenguaje'),
  ('PRECIO_SALIDA_USD_MTOK',   '10.00','DECIMAL', 0, 1000, 'Precio en dólares por millón de tokens de salida del modelo de lenguaje'),
  ('MODELO_RESPALDO',          '',     'TEXTO',   NULL::numeric, NULL::numeric, 'Modelo de lenguaje de respaldo ante un rechazo; vacío significa desactivado'),
  ('IDIOMA_RESPUESTA_DEFECTO', 'es',   'TEXTO',   NULL::numeric, NULL::numeric, 'Idioma de la recomendación cuando la consulta no indica otro (es o en)')
) AS v(clave, valor, tipo, vmin, vmax, descr)
WHERE NOT EXISTS (SELECT 1 FROM configuracion.parametro_sistema p WHERE p.clave = v.clave);
