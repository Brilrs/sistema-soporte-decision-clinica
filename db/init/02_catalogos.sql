-- ============================================================================
-- CDSS Anemia Infantil · Catálogos iniciales (Sprint 0)
-- Se ejecuta después de 01_esquema.sql.
-- Los valores clínicos marcados con [VERIFICAR] deben contrastarse con el
-- texto oficial de la NTS N.° 213-MINSA/DGIESP-2024 y la guía OMS (2024)
-- antes de la validación con usuarios. Todos se pueden modificar desde la
-- pantalla de parámetros clínicos (M12) sin cambiar el código.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Usuario técnico del sistema: dueño de las cargas iniciales.
-- No puede iniciar sesión (hash inválido y cuenta inactiva).
-- ---------------------------------------------------------------------------
INSERT INTO seguridad.usuario (id_usuario, id_rol, nombre_completo, nombre_usuario, hash_contrasena, activo)
SELECT '00000000-0000-0000-0000-000000000001', id_rol, 'Sistema (carga inicial)', 'sistema', '!', false
FROM seguridad.rol WHERE nombre = 'Administrador';

-- ---------------------------------------------------------------------------
-- Permisos por rol (RBAC)
-- ---------------------------------------------------------------------------
INSERT INTO seguridad.rol_permiso (id_rol, id_permiso)
SELECT r.id_rol, p.id_permiso
FROM seguridad.rol r
JOIN seguridad.permiso p ON p.codigo = ANY (
  CASE r.nombre
    WHEN 'Enfermera CRED'   THEN ARRAY['REGISTRAR_PACIENTE','REALIZAR_CONSULTA','EXPORTAR_REPORTE']
    WHEN 'Médico'           THEN ARRAY['REGISTRAR_PACIENTE','REALIZAR_CONSULTA','EXPORTAR_REPORTE']
    WHEN 'Nutricionista'    THEN ARRAY['REGISTRAR_PACIENTE','REALIZAR_CONSULTA','EXPORTAR_REPORTE']
    WHEN 'Coordinador CRED' THEN ARRAY['REALIZAR_CONSULTA','EXPORTAR_REPORTE','CONFIGURAR_PARAMETROS','VER_AUDITORIA']
    WHEN 'Administrador'    THEN ARRAY['ADMINISTRAR_USUARIOS','ADMINISTRAR_GUIAS','CONFIGURAR_PARAMETROS','VER_AUDITORIA']
  END);

-- ---------------------------------------------------------------------------
-- Descriptores MeSH de los síntomas [VERIFICAR en meshb.nlm.nih.gov]
-- ---------------------------------------------------------------------------
UPDATE clinico.sintoma SET descriptor_mesh = d.mesh
FROM (VALUES ('Palidez', 'D010167'),             -- Pallor
             ('Hiporexia', 'D000855'),           -- Anorexia
             ('Irritabilidad', 'D007508'),       -- Irritable Mood
             ('Fatiga o somnolencia', 'D005221'),-- Fatigue
             ('Retraso del desarrollo', 'D002658')) AS d(nombre, mesh) -- Developmental Disabilities
WHERE clinico.sintoma.nombre = d.nombre;

-- ---------------------------------------------------------------------------
-- Distritos con altitud de referencia (msnm) [VERIFICAR con INEI]
-- San Luis y distritos vecinos de Lima, más capitales de altura para
-- probar el ajuste de hemoglobina por altitud.
-- ---------------------------------------------------------------------------
INSERT INTO clinico.distrito (ubigeo, nombre, provincia, departamento, altitud_msnm) VALUES
  ('150134', 'San Luis',       'Lima',       'Lima',     160),
  ('150103', 'Ate',            'Lima',       'Lima',     355),
  ('150111', 'El Agustino',    'Lima',       'Lima',     190),
  ('150115', 'La Victoria',    'Lima',       'Lima',     133),
  ('150130', 'San Borja',      'Lima',       'Lima',     170),
  ('150137', 'Santa Anita',    'Lima',       'Lima',     240),
  ('150101', 'Lima',           'Lima',       'Lima',     154),
  ('040101', 'Arequipa',       'Arequipa',   'Arequipa', 2335),
  ('120101', 'Huancayo',       'Huancayo',   'Junín',    3259),
  ('080101', 'Cusco',          'Cusco',      'Cusco',    3399),
  ('210101', 'Puno',           'Puno',       'Puno',     3827),
  ('190101', 'Chaupimarca',    'Pasco',      'Pasco',    4380);

-- ---------------------------------------------------------------------------
-- Documentos de referencia de los parámetros clínicos.
-- Quedan PENDIENTES de indexación, sin ruta ni hash: el pipeline de
-- indexación (Sprint 2) los completa al cargar el PDF real.
-- La NTS 213 fue aprobada por la RM 251-2024/MINSA (08/04/2024) y modificada
-- por la RM 429-2024/MINSA (18/06/2024), cuyo Anexo trae 12 modificaciones.
-- ---------------------------------------------------------------------------
INSERT INTO conocimiento.documento_fuente
  (id_documento, titulo, codigo_documento, entidad_emisora, tipo_documento, nivel, anio_publicacion,
   fecha_publicacion, version, idioma, pagina_inicio_cuerpo, pagina_fin_cuerpo, cargado_por)
VALUES
  ('10000000-0000-0000-0000-000000000213',
   'Norma técnica de salud para la prevención y control de la anemia', 'NTS 213-MINSA/DGIESP-2024',
   'MINSA', 'NORMA_TECNICA', 1, 2024, DATE '2024-04-08', 'RM 251-2024/MINSA', 'es', 4, 36,
   '00000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000429',
   'NTS 213-MINSA/DGIESP-2024 modificada por RM 429-2024/MINSA', 'RM 429-2024/MINSA',
   'MINSA', 'RESOLUCION', 1, 2024, DATE '2024-06-18', 'RM 429-2024/MINSA', 'es', 4, 11,
   '00000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000002024',
   'Guideline on haemoglobin cutoffs to define anaemia in individuals and populations', 'OMS 2024',
   'OMS', 'GUIA', 1, 2024, NULL, NULL, 'en', 22, 55, '00000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000002016',
   'Guideline: daily iron supplementation in infants and children', 'OMS 2016',
   'OMS', 'GUIA', 1, 2016, NULL, NULL, 'en', 13, 28, '00000000-0000-0000-0000-000000000001');

-- ---------------------------------------------------------------------------
-- Puntos de corte de hemoglobina (g/dL, a nivel del mar) [VERIFICAR]
-- 6 a 23 meses: sin anemia >= 10,5 · leve 9,5-10,4 · moderada 7,0-9,4 · severa < 7,0
-- 24 a 59 meses: sin anemia >= 11,0 · leve 10,0-10,9 · moderada 7,0-9,9 · severa < 7,0
-- ---------------------------------------------------------------------------
INSERT INTO configuracion.umbral_hemoglobina
  (id_documento, id_categoria, edad_min_meses, edad_max_meses, hb_min_g_dl, hb_max_g_dl, modificado_por)
SELECT '10000000-0000-0000-0000-000000002024', c.id_categoria, v.emin, v.emax, v.hmin, v.hmax,
       '00000000-0000-0000-0000-000000000001'
FROM (VALUES
  ('SIN_ANEMIA',      6, 23, 10.5, NULL),
  ('ANEMIA_LEVE',     6, 23,  9.5, 10.4),
  ('ANEMIA_MODERADA', 6, 23,  7.0,  9.4),
  ('ANEMIA_SEVERA',   6, 23, NULL,  6.9),
  ('SIN_ANEMIA',     24, 59, 11.0, NULL),
  ('ANEMIA_LEVE',    24, 59, 10.0, 10.9),
  ('ANEMIA_MODERADA',24, 59,  7.0,  9.9),
  ('ANEMIA_SEVERA',  24, 59, NULL,  6.9)
) AS v(cat, emin, emax, hmin, hmax)
JOIN configuracion.categoria_anemia c ON c.nombre = v.cat;

-- ---------------------------------------------------------------------------
-- Ajuste de hemoglobina por altitud (g/dL que se restan) [VERIFICAR]
-- Valores de la guía OMS (2024) por rangos de 500 m. Los dos últimos rangos
-- siguen la Tabla 1 del Anexo de la RM 429-2024/MINSA (modificación 2).
-- ---------------------------------------------------------------------------
INSERT INTO configuracion.ajuste_altitud
  (id_documento, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, modificado_por)
SELECT v.doc::uuid, v.amin, v.amax, v.aj, '00000000-0000-0000-0000-000000000001'
FROM (VALUES
  ('10000000-0000-0000-0000-000000002024',    0,  499, 0.0),
  ('10000000-0000-0000-0000-000000002024',  500,  999, 0.4),
  ('10000000-0000-0000-0000-000000002024', 1000, 1499, 0.8),
  ('10000000-0000-0000-0000-000000002024', 1500, 1999, 1.1),
  ('10000000-0000-0000-0000-000000002024', 2000, 2499, 1.4),
  ('10000000-0000-0000-0000-000000002024', 2500, 2999, 1.8),
  ('10000000-0000-0000-0000-000000002024', 3000, 3499, 2.1),
  ('10000000-0000-0000-0000-000000002024', 3500, 3999, 2.5),
  ('10000000-0000-0000-0000-000000002024', 4000, 4499, 2.9),
  ('10000000-0000-0000-0000-000000000429', 4500, 4999, 3.3),
  ('10000000-0000-0000-0000-000000000429', 5000, 5500, 4.0)
) AS v(doc, amin, amax, aj);

-- ---------------------------------------------------------------------------
-- Parámetros del sistema (valores iniciales del diseño, OE2 sección 4)
-- ---------------------------------------------------------------------------
INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, modificado_por)
SELECT v.clave, v.valor, v.tipo, v.vmin, v.vmax, v.descr, '00000000-0000-0000-0000-000000000001'
FROM (VALUES
  ('DIAS_VIGENCIA_TAMIZAJE',     '30',  'ENTERO',  1,    365,  'Días durante los que un tamizaje se considera vigente para evaluar'),
  ('EDAD_MIN_CLASIFICACION',     '6',   'ENTERO',  0,    59,   'Edad mínima en meses cubierta por los puntos de corte'),
  ('EDAD_MAX_CLASIFICACION',     '59',  'ENTERO',  0,    59,   'Edad máxima en meses cubierta por los puntos de corte'),
  ('TAMANO_FRAGMENTO_TOKENS',    '500', 'ENTERO',  100,  1000, 'Tamaño objetivo de cada fragmento en la indexación'),
  ('TAMANO_MAX_FRAGMENTO_TOKENS','800', 'ENTERO',  200,  1500, 'Tamaño máximo de un fragmento'),
  ('SOLAPAMIENTO_TOKENS',        '80',  'ENTERO',  0,    200,  'Tokens compartidos entre fragmentos consecutivos'),
  ('CANDIDATOS_BUSQUEDA',        '20',  'ENTERO',  5,    100,  'Candidatos por método de búsqueda (BM25 y densa)'),
  ('CANDIDATOS_BUSQUEDA_AMPLIADA','40', 'ENTERO',  5,    200,  'Candidatos por método en la búsqueda ampliada del reintento'),
  ('RRF_K',                      '60',  'ENTERO',  1,    200,  'Constante k de Reciprocal Rank Fusion'),
  ('FRAGMENTOS_ENVIADOS',        '5',   'ENTERO',  1,    10,   'Fragmentos enviados al modelo de lenguaje'),
  ('UMBRAL_RELEVANCIA',          '0.60','DECIMAL', 0,    1,    'Puntaje mínimo del reranker para considerar suficiente la evidencia'),
  ('REINTENTOS_MAXIMOS',         '1',   'ENTERO',  0,    1,    'Reintentos permitidos por consulta'),
  ('MODELO_LLM',                 'claude-sonnet-5-5', 'TEXTO', NULL, NULL, 'Identificador del modelo de lenguaje'),
  ('TEMPERATURA_LLM',            '0',   'DECIMAL', 0,    1,    'Temperatura del modelo de lenguaje'),
  ('MAX_TOKENS_SALIDA',          '1000','ENTERO',  100,  4000, 'Longitud máxima de la respuesta del modelo'),
  ('TIMEOUT_LLM_S',              '15',  'ENTERO',  3,    60,   'Tiempo máximo de espera de la API del modelo en segundos'),
  ('VERSION_PROMPT',             'v1.0','TEXTO',   NULL, NULL, 'Versión vigente del prompt clínico'),
  ('UMBRAL_DOMINIO',             '0.50','DECIMAL', 0,    1,    'Similitud mínima con las consultas de referencia del dominio (valor provisional, se calibra con las pruebas de recuperación)'),
  ('PRECIO_ENTRADA_USD_MTOK',    '2.00','DECIMAL', 0,    1000, 'Precio en dólares por millón de tokens de entrada del modelo de lenguaje'),
  ('PRECIO_SALIDA_USD_MTOK',     '10.00','DECIMAL',0,    1000, 'Precio en dólares por millón de tokens de salida del modelo de lenguaje'),
  ('MODELO_RESPALDO',            '',    'TEXTO',   NULL, NULL, 'Modelo de lenguaje de respaldo ante un rechazo; vacío significa desactivado'),
  ('IDIOMA_RESPUESTA_DEFECTO',   'es',  'TEXTO',   NULL, NULL, 'Idioma de la recomendación cuando la consulta no indica otro (es o en)'),
  ('CANDIDATOS_RERANKER',        '20',  'ENTERO',  1,    100,  'Candidatos de la fusión RRF que evalúa el reranker'),
  ('MAX_LONGITUD_RERANKER',      '1024','ENTERO',  64,   1024, 'Tokens máximos de cada par consulta y fragmento en el reranker')
) AS v(clave, valor, tipo, vmin, vmax, descr);

-- El modelo vigente no admite el parámetro de temperatura: el valor se cierra
-- y se conserva en el historial.
UPDATE configuracion.parametro_sistema SET vigente_hasta = now()
 WHERE clave = 'TEMPERATURA_LLM' AND vigente_hasta IS NULL;

-- Parámetros definitivos de la recuperación (migración 005): versiones nuevas de
-- CANDIDATOS_RERANKER, MAX_LONGITUD_RERANKER, UMBRAL_RELEVANCIA y UMBRAL_DOMINIO;
-- los valores iniciales quedan cerrados en el historial.
WITH nuevos (clave, valor_inicial, valor, descripcion) AS (VALUES
  ('CANDIDATOS_RERANKER',   '20',   '8',    'Candidatos de la fusión RRF que evalúa el reranker (bge-reranker-v2-m3 ONNX int8)'),
  ('MAX_LONGITUD_RERANKER', '1024', '256',  'Tokens máximos de cada par consulta y fragmento en el reranker'),
  ('UMBRAL_RELEVANCIA',     '0.60', '0.15', 'Puntaje mínimo del reranker para considerar suficiente la evidencia (calibrado con el motor ONNX int8)'),
  ('UMBRAL_DOMINIO',        '0.50', '0.65', 'Similitud mínima con las consultas de referencia del dominio (calibrada con las consultas de referencia)')
),
cerrados AS (
  UPDATE configuracion.parametro_sistema p
     SET vigente_hasta = now()
    FROM nuevos n
   WHERE p.clave = n.clave AND p.vigente_hasta IS NULL AND p.valor = n.valor_inicial
  RETURNING p.clave, p.tipo_dato, p.valor_minimo, p.valor_maximo
)
INSERT INTO configuracion.parametro_sistema
  (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, vigente_desde, modificado_por)
SELECT c.clave, n.valor, c.tipo_dato, c.valor_minimo, c.valor_maximo, n.descripcion, now(),
       '00000000-0000-0000-0000-000000000001'
FROM cerrados c
JOIN nuevos n USING (clave);
