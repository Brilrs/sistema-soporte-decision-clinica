-- ============================================================================
-- Sistema de Soporte a la Decisión Clínica (CDSS) · Anemia infantil, servicio CRED
-- Centro de Salud de San Luis · Script de creación de la base de datos
-- Motor: PostgreSQL 16
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA seguridad;
COMMENT ON SCHEMA seguridad IS 'Seguridad y acceso: Cuentas del personal de salud, roles y permisos para el control de acceso basado en roles.';
CREATE SCHEMA clinico;
COMMENT ON SCHEMA clinico IS 'Datos clínicos del paciente: Paciente seudonimizado, tabla de correspondencia cifrada, tamizajes de cada control CRED, síntomas y resultado del cálculo clínico determinístico.';
CREATE SCHEMA asistencia;
COMMENT ON SCHEMA asistencia IS 'Consulta clínica asistida (RAG): Consultas del profesional, intentos de generación, fragmentos recuperados, recomendaciones verificadas, citas, decisiones clínicas y reportes.';
CREATE SCHEMA conocimiento;
COMMENT ON SCHEMA conocimiento IS 'Base de conocimiento: Catálogo de guías clínicas MINSA/OMS y sus fragmentos indexados; espejo relacional de la colección vectorial.';
CREATE SCHEMA configuracion;
COMMENT ON SCHEMA configuracion IS 'Parámetros clínicos y del sistema: Puntos de corte de hemoglobina, ajuste por altitud, categorías de anemia y parámetros de recuperación y verificación, todos versionados.';
CREATE SCHEMA auditoria;
COMMENT ON SCHEMA auditoria IS 'Auditoría: Bitácora de eventos de solo inserción para la trazabilidad de las acciones de los usuarios.';

-- ---------------------------------------------------------------------------
-- seguridad.rol
-- ---------------------------------------------------------------------------
CREATE TABLE seguridad.rol (
  id_rol SMALLSERIAL PRIMARY KEY,
  nombre VARCHAR(50) NOT NULL UNIQUE,
  descripcion VARCHAR(200),
  activo BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON TABLE seguridad.rol IS 'Catálogo de perfiles del personal que utiliza el sistema (Enfermera CRED, Médico, Nutricionista, Coordinador CRED y Administrador). Cada usuario pertenece a un único rol, que determina las funciones habilitadas.';
COMMENT ON COLUMN seguridad.rol.id_rol IS 'Identificador del rol.';
COMMENT ON COLUMN seguridad.rol.nombre IS 'Nombre del rol mostrado en la interfaz.';
COMMENT ON COLUMN seguridad.rol.descripcion IS 'Descripción de las responsabilidades del rol.';
COMMENT ON COLUMN seguridad.rol.activo IS 'Indica si el rol puede asignarse a nuevos usuarios.';

-- ---------------------------------------------------------------------------
-- seguridad.permiso
-- ---------------------------------------------------------------------------
CREATE TABLE seguridad.permiso (
  id_permiso SMALLSERIAL PRIMARY KEY,
  codigo VARCHAR(50) NOT NULL UNIQUE,
  descripcion VARCHAR(200) NOT NULL
);
COMMENT ON TABLE seguridad.permiso IS 'Catálogo de acciones protegidas del sistema: registrar pacientes, realizar consultas, exportar reportes, configurar parámetros, administrar guías, administrar usuarios y revisar la auditoría.';
COMMENT ON COLUMN seguridad.permiso.id_permiso IS 'Identificador del permiso.';
COMMENT ON COLUMN seguridad.permiso.codigo IS 'Código único de la acción protegida (p. ej., REALIZAR_CONSULTA).';
COMMENT ON COLUMN seguridad.permiso.descripcion IS 'Descripción de la acción que habilita el permiso.';

-- ---------------------------------------------------------------------------
-- seguridad.rol_permiso
-- ---------------------------------------------------------------------------
CREATE TABLE seguridad.rol_permiso (
  id_rol SMALLINT NOT NULL REFERENCES seguridad.rol (id_rol),
  id_permiso SMALLINT NOT NULL REFERENCES seguridad.permiso (id_permiso),
  PRIMARY KEY (id_rol, id_permiso)
);
COMMENT ON TABLE seguridad.rol_permiso IS 'Entidad asociativa que resuelve la relación de muchos a muchos entre roles y permisos.';
COMMENT ON COLUMN seguridad.rol_permiso.id_rol IS 'Rol al que se otorga el permiso.';
COMMENT ON COLUMN seguridad.rol_permiso.id_permiso IS 'Permiso otorgado.';
CREATE INDEX ix_rol_permiso_id_permiso ON seguridad.rol_permiso (id_permiso);

-- ---------------------------------------------------------------------------
-- seguridad.usuario
-- ---------------------------------------------------------------------------
CREATE TABLE seguridad.usuario (
  id_usuario UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_rol SMALLINT NOT NULL REFERENCES seguridad.rol (id_rol),
  nombre_completo VARCHAR(150) NOT NULL,
  nombre_usuario VARCHAR(50) NOT NULL UNIQUE,
  correo_institucional VARCHAR(150) UNIQUE,
  hash_contrasena VARCHAR(255) NOT NULL,
  activo BOOLEAN NOT NULL DEFAULT true,
  intentos_fallidos SMALLINT NOT NULL DEFAULT 0,
  ultimo_acceso TIMESTAMPTZ,
  fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT now(),
  fecha_desactivacion TIMESTAMPTZ
);
COMMENT ON TABLE seguridad.usuario IS 'Cuenta institucional de cada profesional de salud o administrador. Almacena únicamente el hash de la contraseña y los datos necesarios para la autenticación y la trazabilidad de sus acciones.';
COMMENT ON COLUMN seguridad.usuario.id_usuario IS 'Identificador del usuario.';
COMMENT ON COLUMN seguridad.usuario.id_rol IS 'Rol asignado al usuario.';
COMMENT ON COLUMN seguridad.usuario.nombre_completo IS 'Nombre y apellidos del profesional.';
COMMENT ON COLUMN seguridad.usuario.nombre_usuario IS 'Usuario de inicio de sesión (p. ej., enf.rojas).';
COMMENT ON COLUMN seguridad.usuario.correo_institucional IS 'Correo institucional del profesional.';
COMMENT ON COLUMN seguridad.usuario.hash_contrasena IS 'Hash de la contraseña generado con un algoritmo adaptativo (Argon2id).';
COMMENT ON COLUMN seguridad.usuario.activo IS 'Estado de la cuenta; una cuenta inactiva no puede iniciar sesión.';
COMMENT ON COLUMN seguridad.usuario.intentos_fallidos IS 'Intentos de inicio de sesión fallidos consecutivos, para el bloqueo temporal.';
COMMENT ON COLUMN seguridad.usuario.ultimo_acceso IS 'Fecha y hora del último inicio de sesión exitoso.';
COMMENT ON COLUMN seguridad.usuario.fecha_creacion IS 'Fecha y hora de creación de la cuenta.';
COMMENT ON COLUMN seguridad.usuario.fecha_desactivacion IS 'Fecha y hora en que la cuenta fue desactivada.';
CREATE INDEX ix_usuario_id_rol ON seguridad.usuario (id_rol);

-- ---------------------------------------------------------------------------
-- clinico.distrito
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.distrito (
  ubigeo CHAR(6) PRIMARY KEY,
  nombre VARCHAR(80) NOT NULL,
  provincia VARCHAR(80) NOT NULL,
  departamento VARCHAR(80) NOT NULL,
  altitud_msnm INTEGER NOT NULL CHECK (altitud_msnm BETWEEN 0 AND 5500)
);
COMMENT ON TABLE clinico.distrito IS 'Catálogo de distritos con su altitud de referencia. Permite derivar la altitud de residencia del niño a partir del distrito registrado, sin almacenar ni transmitir la dirección (generalización 4.2).';
COMMENT ON COLUMN clinico.distrito.ubigeo IS 'Código de ubicación geográfica del INEI.';
COMMENT ON COLUMN clinico.distrito.nombre IS 'Nombre del distrito.';
COMMENT ON COLUMN clinico.distrito.provincia IS 'Provincia a la que pertenece el distrito.';
COMMENT ON COLUMN clinico.distrito.departamento IS 'Departamento al que pertenece el distrito.';
COMMENT ON COLUMN clinico.distrito.altitud_msnm IS 'Altitud de referencia del distrito en metros sobre el nivel del mar.';

-- ---------------------------------------------------------------------------
-- clinico.paciente
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.paciente (
  id_paciente UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ubigeo_residencia CHAR(6) NOT NULL REFERENCES clinico.distrito (ubigeo),
  fecha_nacimiento DATE NOT NULL,
  sexo CHAR(1) NOT NULL CHECK (sexo IN ('M','F')),
  edad_gestacional_nacer VARCHAR(15) NOT NULL DEFAULT 'NO_REGISTRADO' CHECK (edad_gestacional_nacer IN ('A_TERMINO','PRETERMINO','NO_REGISTRADO')),
  bajo_peso_nacer BOOLEAN,
  registrado_por UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE clinico.paciente IS 'Registro seudonimizado del niño atendido en el servicio CRED. Contiene solo los datos requeridos para el cálculo clínico; los identificadores directos se almacenan por separado y cifrados en paciente_identidad. El identificador del paciente actúa como seudónimo interno.';
COMMENT ON COLUMN clinico.paciente.id_paciente IS 'Seudónimo interno del paciente.';
COMMENT ON COLUMN clinico.paciente.ubigeo_residencia IS 'Distrito de residencia, del que se obtiene la altitud.';
COMMENT ON COLUMN clinico.paciente.fecha_nacimiento IS 'Fecha de nacimiento; permanece en el servidor y se transforma en edad en meses antes de cualquier envío.';
COMMENT ON COLUMN clinico.paciente.sexo IS 'Sexo del niño.';
COMMENT ON COLUMN clinico.paciente.edad_gestacional_nacer IS 'Condición al nacer: A_TERMINO, PRETERMINO o NO_REGISTRADO.';
COMMENT ON COLUMN clinico.paciente.bajo_peso_nacer IS 'Antecedente de bajo peso al nacer.';
COMMENT ON COLUMN clinico.paciente.registrado_por IS 'Usuario que registró al paciente.';
COMMENT ON COLUMN clinico.paciente.fecha_registro IS 'Fecha y hora del registro.';
CREATE INDEX ix_paciente_ubigeo_residencia ON clinico.paciente (ubigeo_residencia);
CREATE INDEX ix_paciente_registrado_por ON clinico.paciente (registrado_por);

-- ---------------------------------------------------------------------------
-- clinico.paciente_identidad
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.paciente_identidad (
  id_paciente UUID PRIMARY KEY REFERENCES clinico.paciente (id_paciente),
  nombres_apellidos_cifrado BYTEA NOT NULL,
  dni_cifrado BYTEA NOT NULL,
  dni_hash CHAR(64) NOT NULL UNIQUE,
  numero_hc_cifrado BYTEA NOT NULL,
  numero_hc_hash CHAR(64) NOT NULL UNIQUE,
  direccion_cifrada BYTEA,
  fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE clinico.paciente_identidad IS 'Tabla de correspondencia entre el seudónimo y la identidad real del paciente. Sus columnas se cifran a nivel de campo y solo se descifran en el servidor para mostrar la ficha al profesional (re-vinculación 7.1). Ningún componente que construye la solicitud al proveedor del LLM tiene permiso de lectura sobre esta tabla.';
COMMENT ON COLUMN clinico.paciente_identidad.id_paciente IS 'Paciente al que corresponde la identidad (relación 1:1).';
COMMENT ON COLUMN clinico.paciente_identidad.nombres_apellidos_cifrado IS 'Nombres y apellidos cifrados (AES-256).';
COMMENT ON COLUMN clinico.paciente_identidad.dni_cifrado IS 'Número de DNI cifrado.';
COMMENT ON COLUMN clinico.paciente_identidad.dni_hash IS 'HMAC-SHA256 del DNI para la búsqueda exacta sin descifrar.';
COMMENT ON COLUMN clinico.paciente_identidad.numero_hc_cifrado IS 'Número de historia clínica cifrado.';
COMMENT ON COLUMN clinico.paciente_identidad.numero_hc_hash IS 'HMAC-SHA256 del número de historia clínica para la búsqueda exacta.';
COMMENT ON COLUMN clinico.paciente_identidad.direccion_cifrada IS 'Dirección de residencia cifrada.';
COMMENT ON COLUMN clinico.paciente_identidad.fecha_actualizacion IS 'Última modificación de los datos de identidad.';

-- ---------------------------------------------------------------------------
-- clinico.sintoma
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.sintoma (
  id_sintoma SMALLSERIAL PRIMARY KEY,
  nombre VARCHAR(60) NOT NULL UNIQUE,
  descriptor_mesh VARCHAR(12)
);
COMMENT ON TABLE clinico.sintoma IS 'Catálogo de síntomas observables asociados a la anemia, con su descriptor MeSH para la normalización de términos.';
COMMENT ON COLUMN clinico.sintoma.id_sintoma IS 'Identificador del síntoma.';
COMMENT ON COLUMN clinico.sintoma.nombre IS 'Nombre del síntoma (palidez, hiporexia, irritabilidad, fatiga o somnolencia, retraso del desarrollo, otro).';
COMMENT ON COLUMN clinico.sintoma.descriptor_mesh IS 'Identificador del descriptor MeSH equivalente, usado en la normalización (2.4).';

-- ---------------------------------------------------------------------------
-- conocimiento.documento_fuente
-- ---------------------------------------------------------------------------
CREATE TABLE conocimiento.documento_fuente (
  id_documento UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  titulo VARCHAR(255) NOT NULL,
  codigo_documento VARCHAR(80),
  entidad_emisora VARCHAR(10) NOT NULL CHECK (entidad_emisora IN ('MINSA','OMS','OTRA')),
  tipo_documento VARCHAR(20) NOT NULL CHECK (tipo_documento IN ('NORMA_TECNICA','GUIA','DIRECTIVA','RESOLUCION','LITERATURA')),
  nivel SMALLINT NOT NULL CHECK (nivel IN (1,2)),
  anio_publicacion SMALLINT NOT NULL,
  version VARCHAR(20),
  ruta_blob VARCHAR(300) NOT NULL,
  hash_archivo CHAR(64) NOT NULL UNIQUE,
  estado VARCHAR(10) NOT NULL DEFAULT 'VIGENTE' CHECK (estado IN ('VIGENTE','OBSOLETA')),
  estado_indexacion VARCHAR(12) NOT NULL DEFAULT 'PENDIENTE' CHECK (estado_indexacion IN ('PENDIENTE','EN_PROCESO','COMPLETADA','ERROR')),
  total_fragmentos INTEGER NOT NULL DEFAULT 0,
  id_documento_reemplazado UUID REFERENCES conocimiento.documento_fuente (id_documento),
  cargado_por UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  fecha_carga TIMESTAMPTZ NOT NULL DEFAULT now(),
  retirado_por UUID REFERENCES seguridad.usuario (id_usuario),
  fecha_retiro TIMESTAMPTZ,
  motivo_retiro VARCHAR(250)
);
COMMENT ON TABLE conocimiento.documento_fuente IS 'Catálogo de las guías clínicas y documentos que conforman la base de conocimiento. El nivel 1 agrupa las fuentes citables (normas MINSA y guías OMS) y el nivel 2, la literatura metodológica que no se cita al usuario. Los documentos no se eliminan: al retirarse pasan a estado OBSOLETA para conservar la trazabilidad de las evaluaciones anteriores.';
COMMENT ON COLUMN conocimiento.documento_fuente.id_documento IS 'Identificador del documento.';
COMMENT ON COLUMN conocimiento.documento_fuente.titulo IS 'Título oficial del documento.';
COMMENT ON COLUMN conocimiento.documento_fuente.codigo_documento IS 'Código o número de la norma (p. ej., NTS 213-MINSA/DGIESP-2024).';
COMMENT ON COLUMN conocimiento.documento_fuente.entidad_emisora IS 'MINSA, OMS u OTRA.';
COMMENT ON COLUMN conocimiento.documento_fuente.tipo_documento IS 'NORMA_TECNICA, GUIA, DIRECTIVA, RESOLUCION o LITERATURA.';
COMMENT ON COLUMN conocimiento.documento_fuente.nivel IS '1 = citable clínicamente; 2 = respaldo metodológico.';
COMMENT ON COLUMN conocimiento.documento_fuente.anio_publicacion IS 'Año de publicación.';
COMMENT ON COLUMN conocimiento.documento_fuente.version IS 'Versión del documento.';
COMMENT ON COLUMN conocimiento.documento_fuente.ruta_blob IS 'Ubicación del PDF original en Azure Blob Storage.';
COMMENT ON COLUMN conocimiento.documento_fuente.hash_archivo IS 'SHA-256 del archivo, para evitar cargas duplicadas.';
COMMENT ON COLUMN conocimiento.documento_fuente.estado IS 'VIGENTE u OBSOLETA.';
COMMENT ON COLUMN conocimiento.documento_fuente.estado_indexacion IS 'PENDIENTE, EN_PROCESO, COMPLETADA o ERROR.';
COMMENT ON COLUMN conocimiento.documento_fuente.total_fragmentos IS 'Número de fragmentos generados en la indexación.';
COMMENT ON COLUMN conocimiento.documento_fuente.id_documento_reemplazado IS 'Documento anterior al que este reemplaza (p. ej., una norma derogada).';
COMMENT ON COLUMN conocimiento.documento_fuente.cargado_por IS 'Usuario que cargó el documento.';
COMMENT ON COLUMN conocimiento.documento_fuente.fecha_carga IS 'Fecha y hora de carga.';
COMMENT ON COLUMN conocimiento.documento_fuente.retirado_por IS 'Usuario que retiró el documento.';
COMMENT ON COLUMN conocimiento.documento_fuente.fecha_retiro IS 'Fecha y hora del retiro.';
COMMENT ON COLUMN conocimiento.documento_fuente.motivo_retiro IS 'Justificación del retiro.';
CREATE INDEX ix_documento_fuente_id_documento_reemplazado ON conocimiento.documento_fuente (id_documento_reemplazado);
CREATE INDEX ix_documento_fuente_cargado_por ON conocimiento.documento_fuente (cargado_por);
CREATE INDEX ix_documento_fuente_retirado_por ON conocimiento.documento_fuente (retirado_por);

-- ---------------------------------------------------------------------------
-- conocimiento.fragmento
-- ---------------------------------------------------------------------------
CREATE TABLE conocimiento.fragmento (
  id_fragmento UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_documento UUID NOT NULL REFERENCES conocimiento.documento_fuente (id_documento),
  numero_orden INTEGER NOT NULL,
  seccion VARCHAR(200),
  pagina_inicio SMALLINT,
  pagina_fin SMALLINT,
  texto TEXT NOT NULL,
  numero_tokens SMALLINT NOT NULL,
  terminos_mesh TEXT[],
  conceptos_umls TEXT[],
  modelo_embedding VARCHAR(40) NOT NULL,
  fecha_indexacion TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (id_documento, numero_orden)
);
COMMENT ON TABLE conocimiento.fragmento IS 'Fragmento de texto de un documento, generado por el pipeline de indexación. Su identificador es el mismo que el del vector en ChromaDB, lo que mantiene la correspondencia entre ambos almacenes. El texto se usa además para construir el índice léxico BM25.';
COMMENT ON COLUMN conocimiento.fragmento.id_fragmento IS 'Identificador del fragmento; igual al identificador del vector en ChromaDB.';
COMMENT ON COLUMN conocimiento.fragmento.id_documento IS 'Documento de origen.';
COMMENT ON COLUMN conocimiento.fragmento.numero_orden IS 'Posición del fragmento dentro del documento.';
COMMENT ON COLUMN conocimiento.fragmento.seccion IS 'Sección o capítulo del documento (p. ej., Tratamiento).';
COMMENT ON COLUMN conocimiento.fragmento.pagina_inicio IS 'Página inicial del fragmento.';
COMMENT ON COLUMN conocimiento.fragmento.pagina_fin IS 'Página final del fragmento.';
COMMENT ON COLUMN conocimiento.fragmento.texto IS 'Contenido textual del fragmento.';
COMMENT ON COLUMN conocimiento.fragmento.numero_tokens IS 'Longitud del fragmento en tokens.';
COMMENT ON COLUMN conocimiento.fragmento.terminos_mesh IS 'Descriptores MeSH asignados en la normalización.';
COMMENT ON COLUMN conocimiento.fragmento.conceptos_umls IS 'Identificadores de concepto UMLS (CUI) asignados.';
COMMENT ON COLUMN conocimiento.fragmento.modelo_embedding IS 'Modelo con el que se generó el vector (bge-m3).';
COMMENT ON COLUMN conocimiento.fragmento.fecha_indexacion IS 'Fecha y hora de indexación.';
CREATE INDEX ix_fragmento_id_documento ON conocimiento.fragmento (id_documento);

-- ---------------------------------------------------------------------------
-- configuracion.categoria_anemia
-- ---------------------------------------------------------------------------
CREATE TABLE configuracion.categoria_anemia (
  id_categoria SMALLSERIAL PRIMARY KEY,
  nombre VARCHAR(30) NOT NULL UNIQUE,
  nivel_riesgo VARCHAR(10) NOT NULL CHECK (nivel_riesgo IN ('BAJO','MODERADO','ALTO','MUY_ALTO')),
  requiere_derivacion BOOLEAN NOT NULL DEFAULT false,
  orden SMALLINT NOT NULL UNIQUE
);
COMMENT ON TABLE configuracion.categoria_anemia IS 'Catálogo de las clasificaciones de anemia y su correspondencia con el nivel de riesgo mostrado al usuario.';
COMMENT ON COLUMN configuracion.categoria_anemia.id_categoria IS 'Identificador de la categoría.';
COMMENT ON COLUMN configuracion.categoria_anemia.nombre IS 'SIN_ANEMIA, ANEMIA_LEVE, ANEMIA_MODERADA o ANEMIA_SEVERA.';
COMMENT ON COLUMN configuracion.categoria_anemia.nivel_riesgo IS 'BAJO, MODERADO, ALTO o MUY_ALTO.';
COMMENT ON COLUMN configuracion.categoria_anemia.requiere_derivacion IS 'Indica si la categoría exige derivación.';
COMMENT ON COLUMN configuracion.categoria_anemia.orden IS 'Orden de severidad.';

-- ---------------------------------------------------------------------------
-- configuracion.umbral_hemoglobina
-- ---------------------------------------------------------------------------
CREATE TABLE configuracion.umbral_hemoglobina (
  id_umbral SERIAL PRIMARY KEY,
  id_documento UUID NOT NULL REFERENCES conocimiento.documento_fuente (id_documento),
  id_categoria SMALLINT NOT NULL REFERENCES configuracion.categoria_anemia (id_categoria),
  edad_min_meses SMALLINT NOT NULL,
  edad_max_meses SMALLINT NOT NULL,
  hb_min_g_dl NUMERIC(4,1),
  hb_max_g_dl NUMERIC(4,1),
  vigente_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
  vigente_hasta TIMESTAMPTZ,
  modificado_por UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  CHECK (edad_min_meses <= edad_max_meses)
);
COMMENT ON TABLE configuracion.umbral_hemoglobina IS 'Puntos de corte de hemoglobina a nivel del mar por grupo de edad y categoría, tomados de la norma de referencia. Se versionan mediante el periodo de vigencia; una modificación cierra la fila vigente y crea una nueva.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.id_umbral IS 'Identificador del punto de corte.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.id_documento IS 'Norma de la que procede el valor.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.id_categoria IS 'Categoría a la que corresponde el rango.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.edad_min_meses IS 'Edad mínima del grupo, en meses.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.edad_max_meses IS 'Edad máxima del grupo, en meses.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.hb_min_g_dl IS 'Límite inferior del rango (nulo para la categoría más severa).';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.hb_max_g_dl IS 'Límite superior del rango (nulo para la categoría sin anemia).';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.vigente_desde IS 'Inicio de vigencia.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.vigente_hasta IS 'Fin de vigencia; nulo mientras el valor está vigente.';
COMMENT ON COLUMN configuracion.umbral_hemoglobina.modificado_por IS 'Usuario que registró el valor.';
CREATE INDEX ix_umbral_hemoglobina_id_documento ON configuracion.umbral_hemoglobina (id_documento);
CREATE INDEX ix_umbral_hemoglobina_id_categoria ON configuracion.umbral_hemoglobina (id_categoria);
CREATE INDEX ix_umbral_hemoglobina_modificado_por ON configuracion.umbral_hemoglobina (modificado_por);

-- ---------------------------------------------------------------------------
-- configuracion.ajuste_altitud
-- ---------------------------------------------------------------------------
CREATE TABLE configuracion.ajuste_altitud (
  id_ajuste SERIAL PRIMARY KEY,
  id_documento UUID NOT NULL REFERENCES conocimiento.documento_fuente (id_documento),
  altitud_min_msnm INTEGER NOT NULL,
  altitud_max_msnm INTEGER NOT NULL,
  ajuste_g_dl NUMERIC(3,1) NOT NULL CHECK (ajuste_g_dl >= 0),
  vigente_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
  vigente_hasta TIMESTAMPTZ,
  modificado_por UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  CHECK (altitud_min_msnm <= altitud_max_msnm)
);
COMMENT ON TABLE configuracion.ajuste_altitud IS 'Tabla de ajuste de hemoglobina por rango de altitud de residencia, cargada desde la norma de referencia y aplicada antes de clasificar.';
COMMENT ON COLUMN configuracion.ajuste_altitud.id_ajuste IS 'Identificador del rango de ajuste.';
COMMENT ON COLUMN configuracion.ajuste_altitud.id_documento IS 'Norma de la que procede el ajuste.';
COMMENT ON COLUMN configuracion.ajuste_altitud.altitud_min_msnm IS 'Altitud mínima del rango.';
COMMENT ON COLUMN configuracion.ajuste_altitud.altitud_max_msnm IS 'Altitud máxima del rango.';
COMMENT ON COLUMN configuracion.ajuste_altitud.ajuste_g_dl IS 'Valor que se resta a la hemoglobina observada.';
COMMENT ON COLUMN configuracion.ajuste_altitud.vigente_desde IS 'Inicio de vigencia.';
COMMENT ON COLUMN configuracion.ajuste_altitud.vigente_hasta IS 'Fin de vigencia; nulo mientras el valor está vigente.';
COMMENT ON COLUMN configuracion.ajuste_altitud.modificado_por IS 'Usuario que registró el valor.';
CREATE INDEX ix_ajuste_altitud_id_documento ON configuracion.ajuste_altitud (id_documento);
CREATE INDEX ix_ajuste_altitud_modificado_por ON configuracion.ajuste_altitud (modificado_por);

-- ---------------------------------------------------------------------------
-- configuracion.parametro_sistema
-- ---------------------------------------------------------------------------
CREATE TABLE configuracion.parametro_sistema (
  id_parametro SERIAL PRIMARY KEY,
  clave VARCHAR(50) NOT NULL,
  valor VARCHAR(100) NOT NULL,
  tipo_dato VARCHAR(10) NOT NULL CHECK (tipo_dato IN ('ENTERO','DECIMAL','TEXTO')),
  valor_minimo NUMERIC(10,3),
  valor_maximo NUMERIC(10,3),
  descripcion VARCHAR(250) NOT NULL,
  vigente_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
  vigente_hasta TIMESTAMPTZ,
  modificado_por UUID NOT NULL REFERENCES seguridad.usuario (id_usuario)
);
COMMENT ON TABLE configuracion.parametro_sistema IS 'Parámetros operativos del sistema: días de vigencia del tamizaje, candidatos por búsqueda, fragmentos enviados, umbral de relevancia, reintentos máximos, modelo del LLM y tiempo máximo de espera. Se versionan igual que los parámetros clínicos.';
COMMENT ON COLUMN configuracion.parametro_sistema.id_parametro IS 'Identificador de la versión del parámetro.';
COMMENT ON COLUMN configuracion.parametro_sistema.clave IS 'Nombre del parámetro (p. ej., DIAS_VIGENCIA_TAMIZAJE, UMBRAL_RELEVANCIA).';
COMMENT ON COLUMN configuracion.parametro_sistema.valor IS 'Valor del parámetro.';
COMMENT ON COLUMN configuracion.parametro_sistema.tipo_dato IS 'ENTERO, DECIMAL o TEXTO.';
COMMENT ON COLUMN configuracion.parametro_sistema.valor_minimo IS 'Límite inferior permitido para valores numéricos.';
COMMENT ON COLUMN configuracion.parametro_sistema.valor_maximo IS 'Límite superior permitido para valores numéricos.';
COMMENT ON COLUMN configuracion.parametro_sistema.descripcion IS 'Descripción del efecto del parámetro.';
COMMENT ON COLUMN configuracion.parametro_sistema.vigente_desde IS 'Inicio de vigencia.';
COMMENT ON COLUMN configuracion.parametro_sistema.vigente_hasta IS 'Fin de vigencia; nulo mientras el valor está vigente.';
COMMENT ON COLUMN configuracion.parametro_sistema.modificado_por IS 'Usuario que registró el valor.';
CREATE INDEX ix_parametro_sistema_modificado_por ON configuracion.parametro_sistema (modificado_por);

-- ---------------------------------------------------------------------------
-- clinico.tamizaje
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.tamizaje (
  id_tamizaje UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_paciente UUID NOT NULL REFERENCES clinico.paciente (id_paciente),
  id_usuario UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  fecha_tamizaje DATE NOT NULL,
  edad_meses SMALLINT NOT NULL CHECK (edad_meses BETWEEN 0 AND 59),
  hemoglobina_g_dl NUMERIC(4,1) CHECK (hemoglobina_g_dl BETWEEN 3.0 AND 20.0),
  metodo_medicion VARCHAR(20) CHECK (metodo_medicion IN ('HEMOGLOBINOMETRO','LABORATORIO')),
  peso_kg NUMERIC(5,2) CHECK (peso_kg > 0),
  talla_cm NUMERIC(5,1) CHECK (talla_cm > 0),
  recibe_suplementacion_hierro BOOLEAN,
  lactancia_materna_actual BOOLEAN,
  parasitosis_reciente BOOLEAN,
  observaciones TEXT,
  fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE clinico.tamizaje IS 'Registro de cada control CRED en el que se mide la hemoglobina y se capturan los datos antropométricos y antecedentes del niño. Es la unidad clínica sobre la que se calcula la clasificación y se formulan las consultas. Cuando el niño regresa a un nuevo control se registra un nuevo tamizaje: los datos permanentes del paciente no se vuelven a capturar y los tamizajes anteriores se conservan para el historial y el análisis de la evolución.';
COMMENT ON COLUMN clinico.tamizaje.id_tamizaje IS 'Identificador del tamizaje.';
COMMENT ON COLUMN clinico.tamizaje.id_paciente IS 'Paciente evaluado.';
COMMENT ON COLUMN clinico.tamizaje.id_usuario IS 'Profesional que registró el tamizaje.';
COMMENT ON COLUMN clinico.tamizaje.fecha_tamizaje IS 'Fecha de la medición de hemoglobina.';
COMMENT ON COLUMN clinico.tamizaje.edad_meses IS 'Edad exacta en meses a la fecha del tamizaje, calculada a partir de la fecha de nacimiento.';
COMMENT ON COLUMN clinico.tamizaje.hemoglobina_g_dl IS 'Hemoglobina observada en g/dL; puede quedar pendiente y completarse ante una solicitud de datos faltantes.';
COMMENT ON COLUMN clinico.tamizaje.metodo_medicion IS 'Método de medición: HEMOGLOBINOMETRO o LABORATORIO.';
COMMENT ON COLUMN clinico.tamizaje.peso_kg IS 'Peso del niño en kilogramos.';
COMMENT ON COLUMN clinico.tamizaje.talla_cm IS 'Talla del niño en centímetros.';
COMMENT ON COLUMN clinico.tamizaje.recibe_suplementacion_hierro IS 'Indica si el niño recibe suplementación con hierro.';
COMMENT ON COLUMN clinico.tamizaje.lactancia_materna_actual IS 'Indica si el niño recibe lactancia materna actualmente.';
COMMENT ON COLUMN clinico.tamizaje.parasitosis_reciente IS 'Antecedente de parasitosis reciente.';
COMMENT ON COLUMN clinico.tamizaje.observaciones IS 'Texto libre del profesional; se procesa con el filtro de texto libre (4.3) antes de cualquier uso en la generación.';
COMMENT ON COLUMN clinico.tamizaje.fecha_registro IS 'Fecha y hora del registro.';
CREATE INDEX ix_tamizaje_id_paciente ON clinico.tamizaje (id_paciente);
CREATE INDEX ix_tamizaje_id_usuario ON clinico.tamizaje (id_usuario);

-- ---------------------------------------------------------------------------
-- clinico.tamizaje_sintoma
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.tamizaje_sintoma (
  id_tamizaje UUID NOT NULL REFERENCES clinico.tamizaje (id_tamizaje),
  id_sintoma SMALLINT NOT NULL REFERENCES clinico.sintoma (id_sintoma),
  detalle VARCHAR(150),
  PRIMARY KEY (id_tamizaje, id_sintoma)
);
COMMENT ON TABLE clinico.tamizaje_sintoma IS 'Entidad asociativa que registra los síntomas observados en cada tamizaje.';
COMMENT ON COLUMN clinico.tamizaje_sintoma.id_tamizaje IS 'Tamizaje en el que se observó el síntoma.';
COMMENT ON COLUMN clinico.tamizaje_sintoma.id_sintoma IS 'Síntoma observado.';
COMMENT ON COLUMN clinico.tamizaje_sintoma.detalle IS 'Especificación cuando el síntoma es «Otro».';
CREATE INDEX ix_tamizaje_sintoma_id_sintoma ON clinico.tamizaje_sintoma (id_sintoma);

-- ---------------------------------------------------------------------------
-- clinico.resultado_clasificacion
-- ---------------------------------------------------------------------------
CREATE TABLE clinico.resultado_clasificacion (
  id_tamizaje UUID PRIMARY KEY REFERENCES clinico.tamizaje (id_tamizaje),
  altitud_msnm INTEGER NOT NULL,
  id_ajuste INTEGER NOT NULL REFERENCES configuracion.ajuste_altitud (id_ajuste),
  ajuste_hb_g_dl NUMERIC(3,1) NOT NULL,
  hb_ajustada_g_dl NUMERIC(4,1) NOT NULL,
  id_umbral INTEGER NOT NULL REFERENCES configuracion.umbral_hemoglobina (id_umbral),
  id_categoria SMALLINT NOT NULL REFERENCES configuracion.categoria_anemia (id_categoria),
  nivel_riesgo VARCHAR(10) NOT NULL CHECK (nivel_riesgo IN ('BAJO','MODERADO','ALTO','MUY_ALTO')),
  fecha_calculo TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE clinico.resultado_clasificacion IS 'Resultado del cálculo clínico determinístico (2.3): ajuste de hemoglobina por altitud y clasificación de anemia según la norma vigente. Guarda una instantánea de los valores aplicados para que el resultado histórico no cambie si los parámetros se actualizan.';
COMMENT ON COLUMN clinico.resultado_clasificacion.id_tamizaje IS 'Tamizaje clasificado (relación 1:1).';
COMMENT ON COLUMN clinico.resultado_clasificacion.altitud_msnm IS 'Altitud aplicada en el cálculo.';
COMMENT ON COLUMN clinico.resultado_clasificacion.id_ajuste IS 'Rango de ajuste por altitud aplicado.';
COMMENT ON COLUMN clinico.resultado_clasificacion.ajuste_hb_g_dl IS 'Valor de ajuste restado a la hemoglobina observada.';
COMMENT ON COLUMN clinico.resultado_clasificacion.hb_ajustada_g_dl IS 'Hemoglobina ajustada por altitud.';
COMMENT ON COLUMN clinico.resultado_clasificacion.id_umbral IS 'Punto de corte de hemoglobina aplicado.';
COMMENT ON COLUMN clinico.resultado_clasificacion.id_categoria IS 'Clasificación obtenida (sin anemia, leve, moderada o severa).';
COMMENT ON COLUMN clinico.resultado_clasificacion.nivel_riesgo IS 'Nivel de riesgo mostrado al usuario al momento del cálculo.';
COMMENT ON COLUMN clinico.resultado_clasificacion.fecha_calculo IS 'Fecha y hora del cálculo.';
CREATE INDEX ix_resultado_clasificacion_id_ajuste ON clinico.resultado_clasificacion (id_ajuste);
CREATE INDEX ix_resultado_clasificacion_id_umbral ON clinico.resultado_clasificacion (id_umbral);
CREATE INDEX ix_resultado_clasificacion_id_categoria ON clinico.resultado_clasificacion (id_categoria);

-- ---------------------------------------------------------------------------
-- asistencia.consulta
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.consulta (
  id_consulta UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_consulta_previa UUID REFERENCES asistencia.consulta (id_consulta),
  id_tamizaje UUID NOT NULL REFERENCES clinico.tamizaje (id_tamizaje),
  id_usuario UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  texto_consulta TEXT NOT NULL,
  estado VARCHAR(25) NOT NULL DEFAULT 'EN_PROCESO' CHECK (estado IN ('EN_PROCESO','VERIFICADA','DATOS_FALTANTES','FUERA_DE_DOMINIO','EVIDENCIA_INSUFICIENTE','ERROR')),
  numero_intentos SMALLINT NOT NULL DEFAULT 0 CHECK (numero_intentos BETWEEN 0 AND 2),
  fecha_hora_inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
  fecha_hora_fin TIMESTAMPTZ,
  latencia_total_ms INTEGER CHECK (latencia_total_ms >= 0),
  confirma_tamizaje_no_vigente BOOLEAN NOT NULL DEFAULT false
);
COMMENT ON TABLE asistencia.consulta IS 'Pregunta clínica formulada por el profesional sobre un tamizaje. Registra su estado a lo largo del flujo y el tiempo total de respuesta (RNF3). Las consultas de seguimiento se enlazan con la consulta previa para conservar el contexto de sesión (1.3).';
COMMENT ON COLUMN asistencia.consulta.id_consulta IS 'Identificador de la consulta.';
COMMENT ON COLUMN asistencia.consulta.id_consulta_previa IS 'Consulta anterior de la misma sesión, cuando se trata de una pregunta de seguimiento.';
COMMENT ON COLUMN asistencia.consulta.id_tamizaje IS 'Tamizaje que da contexto clínico a la consulta.';
COMMENT ON COLUMN asistencia.consulta.id_usuario IS 'Profesional que formula la consulta.';
COMMENT ON COLUMN asistencia.consulta.texto_consulta IS 'Texto original de la consulta; permanece en el servidor y nunca se envía al proveedor del LLM.';
COMMENT ON COLUMN asistencia.consulta.estado IS 'EN_PROCESO, VERIFICADA, DATOS_FALTANTES, FUERA_DE_DOMINIO, EVIDENCIA_INSUFICIENTE o ERROR.';
COMMENT ON COLUMN asistencia.consulta.numero_intentos IS 'Intentos de generación ejecutados (máximo dos: inicial y un reintento).';
COMMENT ON COLUMN asistencia.consulta.fecha_hora_inicio IS 'Inicio del procesamiento.';
COMMENT ON COLUMN asistencia.consulta.fecha_hora_fin IS 'Fin del procesamiento.';
COMMENT ON COLUMN asistencia.consulta.latencia_total_ms IS 'Tiempo total de respuesta en milisegundos, usado para el control del percentil 90.';
COMMENT ON COLUMN asistencia.consulta.confirma_tamizaje_no_vigente IS 'Indica que el profesional decidió continuar con un tamizaje que superaba el plazo de vigencia.';
CREATE INDEX ix_consulta_id_consulta_previa ON asistencia.consulta (id_consulta_previa);
CREATE INDEX ix_consulta_id_tamizaje ON asistencia.consulta (id_tamizaje);
CREATE INDEX ix_consulta_id_usuario ON asistencia.consulta (id_usuario);

-- ---------------------------------------------------------------------------
-- asistencia.dato_faltante
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.dato_faltante (
  id_dato_faltante BIGSERIAL PRIMARY KEY,
  id_consulta UUID NOT NULL REFERENCES asistencia.consulta (id_consulta),
  campo VARCHAR(50) NOT NULL,
  mensaje VARCHAR(250) NOT NULL,
  completado BOOLEAN NOT NULL DEFAULT false,
  fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),
  fecha_completado TIMESTAMPTZ
);
COMMENT ON TABLE asistencia.dato_faltante IS 'Solicitud de información que el sistema realiza al profesional cuando faltan datos mínimos para evaluar (2.2), junto con su atención.';
COMMENT ON COLUMN asistencia.dato_faltante.id_dato_faltante IS 'Identificador de la solicitud.';
COMMENT ON COLUMN asistencia.dato_faltante.id_consulta IS 'Consulta que originó la solicitud.';
COMMENT ON COLUMN asistencia.dato_faltante.campo IS 'Campo requerido (p. ej., hemoglobina_g_dl, fecha_tamizaje).';
COMMENT ON COLUMN asistencia.dato_faltante.mensaje IS 'Mensaje mostrado al profesional.';
COMMENT ON COLUMN asistencia.dato_faltante.completado IS 'Indica si el profesional proporcionó el dato.';
COMMENT ON COLUMN asistencia.dato_faltante.fecha_solicitud IS 'Fecha y hora de la solicitud.';
COMMENT ON COLUMN asistencia.dato_faltante.fecha_completado IS 'Fecha y hora en que se completó el dato.';
CREATE INDEX ix_dato_faltante_id_consulta ON asistencia.dato_faltante (id_consulta);

-- ---------------------------------------------------------------------------
-- asistencia.intento_generacion
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.intento_generacion (
  id_intento UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_consulta UUID NOT NULL REFERENCES asistencia.consulta (id_consulta),
  numero_intento SMALLINT NOT NULL CHECK (numero_intento IN (1,2)),
  tipo_busqueda VARCHAR(10) NOT NULL CHECK (tipo_busqueda IN ('INICIAL','AMPLIADA')),
  consulta_reformulada TEXT NOT NULL,
  terminos_normalizados TEXT[],
  candidatos_evaluados SMALLINT NOT NULL,
  relevancia_maxima NUMERIC(4,3),
  umbral_relevancia NUMERIC(4,3) NOT NULL,
  solicitud_enviada JSONB,
  hash_solicitud CHAR(64),
  control_identificadores BOOLEAN,
  modelo_llm VARCHAR(60),
  version_prompt VARCHAR(20),
  tokens_entrada INTEGER CHECK (tokens_entrada >= 0),
  tokens_salida INTEGER CHECK (tokens_salida >= 0),
  costo_usd NUMERIC(8,5) CHECK (costo_usd >= 0),
  latencia_llm_ms INTEGER,
  respuesta_borrador TEXT,
  valida_citas BOOLEAN,
  valida_consistencia BOOLEAN,
  valida_evidencia BOOLEAN,
  resultado VARCHAR(25) NOT NULL CHECK (resultado IN ('APROBADO','REINTENTO','EVIDENCIA_INSUFICIENTE','ERROR')),
  fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (id_consulta, numero_intento)
);
COMMENT ON TABLE asistencia.intento_generacion IS 'Cada ejecución del ciclo recuperación–protección–generación–verificación de una consulta. El primer intento corresponde a la búsqueda inicial y el segundo, al único reintento permitido. Registra la solicitud desidentificada efectivamente enviada al proveedor, el consumo de tokens, el costo y el resultado de cada verificación en línea.';
COMMENT ON COLUMN asistencia.intento_generacion.id_intento IS 'Identificador del intento.';
COMMENT ON COLUMN asistencia.intento_generacion.id_consulta IS 'Consulta a la que pertenece el intento.';
COMMENT ON COLUMN asistencia.intento_generacion.numero_intento IS '1 = búsqueda inicial; 2 = reintento.';
COMMENT ON COLUMN asistencia.intento_generacion.tipo_busqueda IS 'INICIAL o AMPLIADA.';
COMMENT ON COLUMN asistencia.intento_generacion.consulta_reformulada IS 'Consulta reformulada y normalizada (2.4), sin identificadores.';
COMMENT ON COLUMN asistencia.intento_generacion.terminos_normalizados IS 'Términos MeSH/UMLS identificados en la consulta.';
COMMENT ON COLUMN asistencia.intento_generacion.candidatos_evaluados IS 'Número de candidatos evaluados por el reranker.';
COMMENT ON COLUMN asistencia.intento_generacion.relevancia_maxima IS 'Puntaje máximo del reranker en el intento.';
COMMENT ON COLUMN asistencia.intento_generacion.umbral_relevancia IS 'Umbral de relevancia vigente al ejecutar el intento.';
COMMENT ON COLUMN asistencia.intento_generacion.solicitud_enviada IS 'Solicitud mínima desidentificada enviada al proveedor (4.4), que incluye el resumen del tamizaje anterior (Hb, clasificación y meses transcurridos); nula si el intento no llegó a la generación.';
COMMENT ON COLUMN asistencia.intento_generacion.hash_solicitud IS 'SHA-256 de la solicitud enviada, para la verificación de integridad.';
COMMENT ON COLUMN asistencia.intento_generacion.control_identificadores IS 'Resultado del control que confirma la ausencia de identificadores en la solicitud.';
COMMENT ON COLUMN asistencia.intento_generacion.modelo_llm IS 'Identificador del modelo utilizado (p. ej., claude-sonnet-4-5).';
COMMENT ON COLUMN asistencia.intento_generacion.version_prompt IS 'Versión de la plantilla del prompt clínico.';
COMMENT ON COLUMN asistencia.intento_generacion.tokens_entrada IS 'Tokens de entrada facturados.';
COMMENT ON COLUMN asistencia.intento_generacion.tokens_salida IS 'Tokens de salida facturados.';
COMMENT ON COLUMN asistencia.intento_generacion.costo_usd IS 'Costo de la llamada en dólares.';
COMMENT ON COLUMN asistencia.intento_generacion.latencia_llm_ms IS 'Tiempo de respuesta del proveedor en milisegundos.';
COMMENT ON COLUMN asistencia.intento_generacion.respuesta_borrador IS 'Respuesta del LLM antes de la verificación.';
COMMENT ON COLUMN asistencia.intento_generacion.valida_citas IS 'Resultado de 6.1: cada cita corresponde a un fragmento enviado.';
COMMENT ON COLUMN asistencia.intento_generacion.valida_consistencia IS 'Resultado de 6.2: la respuesta es coherente con la clasificación calculada.';
COMMENT ON COLUMN asistencia.intento_generacion.valida_evidencia IS 'Resultado de 6.3: el puntaje del reranker alcanza el umbral.';
COMMENT ON COLUMN asistencia.intento_generacion.resultado IS 'APROBADO, REINTENTO, EVIDENCIA_INSUFICIENTE o ERROR.';
COMMENT ON COLUMN asistencia.intento_generacion.fecha_hora IS 'Fecha y hora del intento.';
CREATE INDEX ix_intento_generacion_id_consulta ON asistencia.intento_generacion (id_consulta);

-- ---------------------------------------------------------------------------
-- asistencia.fragmento_recuperado
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.fragmento_recuperado (
  id_intento UUID NOT NULL REFERENCES asistencia.intento_generacion (id_intento),
  id_fragmento UUID NOT NULL REFERENCES conocimiento.fragmento (id_fragmento),
  posicion_rrf SMALLINT NOT NULL,
  puntaje_rrf NUMERIC(6,5) NOT NULL,
  puntaje_reranker NUMERIC(4,3) NOT NULL,
  posicion_final SMALLINT NOT NULL,
  enviado_al_llm BOOLEAN NOT NULL DEFAULT false,
  etiqueta_cita VARCHAR(8),
  PRIMARY KEY (id_intento, id_fragmento),
  UNIQUE (id_intento, etiqueta_cita)
);
COMMENT ON TABLE asistencia.fragmento_recuperado IS 'Fragmentos candidatos obtenidos en cada intento, con sus posiciones y puntajes de la fusión RRF y del reranker. Los cinco mejor puntuados se marcan como enviados al LLM y reciben una etiqueta de cita.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.id_intento IS 'Intento en el que se recuperó el fragmento.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.id_fragmento IS 'Fragmento recuperado.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.posicion_rrf IS 'Posición tras la fusión Reciprocal Rank Fusion (3.3).';
COMMENT ON COLUMN asistencia.fragmento_recuperado.puntaje_rrf IS 'Puntaje de la fusión RRF.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.puntaje_reranker IS 'Puntaje del reranker clínico (3.4).';
COMMENT ON COLUMN asistencia.fragmento_recuperado.posicion_final IS 'Posición tras el reranking.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.enviado_al_llm IS 'Indica si el fragmento formó parte del top-5 enviado.';
COMMENT ON COLUMN asistencia.fragmento_recuperado.etiqueta_cita IS 'Etiqueta asignada al fragmento enviado (p. ej., F-12).';
CREATE INDEX ix_fragmento_recuperado_id_fragmento ON asistencia.fragmento_recuperado (id_fragmento);

-- ---------------------------------------------------------------------------
-- asistencia.recomendacion
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.recomendacion (
  id_recomendacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_consulta UUID NOT NULL UNIQUE REFERENCES asistencia.consulta (id_consulta),
  id_intento UUID NOT NULL UNIQUE REFERENCES asistencia.intento_generacion (id_intento),
  texto_recomendacion TEXT NOT NULL,
  factores_identificados TEXT[],
  fecha_generacion TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE asistencia.recomendacion IS 'Respuesta clínica que superó la verificación en línea. Solo existe para consultas en estado VERIFICADA y se vincula con el intento aprobado.';
COMMENT ON COLUMN asistencia.recomendacion.id_recomendacion IS 'Identificador de la recomendación.';
COMMENT ON COLUMN asistencia.recomendacion.id_consulta IS 'Consulta respondida (relación 1:1).';
COMMENT ON COLUMN asistencia.recomendacion.id_intento IS 'Intento aprobado que produjo la recomendación.';
COMMENT ON COLUMN asistencia.recomendacion.texto_recomendacion IS 'Recomendación con sus marcas de cita.';
COMMENT ON COLUMN asistencia.recomendacion.factores_identificados IS 'Factores de riesgo identificados y mostrados al profesional.';
COMMENT ON COLUMN asistencia.recomendacion.fecha_generacion IS 'Fecha y hora de la generación.';

-- ---------------------------------------------------------------------------
-- asistencia.cita_evidencia
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.cita_evidencia (
  id_cita BIGSERIAL PRIMARY KEY,
  id_recomendacion UUID NOT NULL REFERENCES asistencia.recomendacion (id_recomendacion),
  id_intento UUID NOT NULL,
  id_fragmento UUID NOT NULL,
  orden SMALLINT NOT NULL,
  texto_citado TEXT NOT NULL,
  FOREIGN KEY (id_intento, id_fragmento) REFERENCES asistencia.fragmento_recuperado (id_intento, id_fragmento),
  UNIQUE (id_recomendacion, id_fragmento)
);
COMMENT ON TABLE asistencia.cita_evidencia IS 'Cada evidencia citada en una recomendación. Referencia al fragmento recuperado en el mismo intento, de modo que la base de datos solo admite citas de fragmentos realmente enviados al LLM (6.1).';
COMMENT ON COLUMN asistencia.cita_evidencia.id_cita IS 'Identificador de la cita.';
COMMENT ON COLUMN asistencia.cita_evidencia.id_recomendacion IS 'Recomendación que contiene la cita.';
COMMENT ON COLUMN asistencia.cita_evidencia.id_intento IS 'Intento del fragmento citado (parte de la clave foránea compuesta).';
COMMENT ON COLUMN asistencia.cita_evidencia.id_fragmento IS 'Fragmento citado (parte de la clave foránea compuesta).';
COMMENT ON COLUMN asistencia.cita_evidencia.orden IS 'Orden de aparición de la cita en la recomendación.';
COMMENT ON COLUMN asistencia.cita_evidencia.texto_citado IS 'Extracto del fragmento mostrado al usuario, conservado como instantánea.';
CREATE INDEX ix_cita_evidencia_id_recomendacion ON asistencia.cita_evidencia (id_recomendacion);

-- ---------------------------------------------------------------------------
-- asistencia.decision_clinica
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.decision_clinica (
  id_decision UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  id_consulta UUID NOT NULL UNIQUE REFERENCES asistencia.consulta (id_consulta),
  id_usuario UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  tipo_decision VARCHAR(25) NOT NULL CHECK (tipo_decision IN ('ACEPTA_RECOMENDACION','MODIFICA_RECOMENDACION','CRITERIO_CLINICO_PROPIO')),
  descripcion TEXT,
  fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE asistencia.decision_clinica IS 'Decisión final que registra el profesional sobre una consulta: acepta la recomendación, la modifica o aplica su propio criterio clínico, en especial cuando la evidencia es insuficiente.';
COMMENT ON COLUMN asistencia.decision_clinica.id_decision IS 'Identificador de la decisión.';
COMMENT ON COLUMN asistencia.decision_clinica.id_consulta IS 'Consulta sobre la que se decide (relación 1:1).';
COMMENT ON COLUMN asistencia.decision_clinica.id_usuario IS 'Profesional responsable de la decisión.';
COMMENT ON COLUMN asistencia.decision_clinica.tipo_decision IS 'ACEPTA_RECOMENDACION, MODIFICA_RECOMENDACION o CRITERIO_CLINICO_PROPIO.';
COMMENT ON COLUMN asistencia.decision_clinica.descripcion IS 'Detalle de la conducta adoptada.';
COMMENT ON COLUMN asistencia.decision_clinica.fecha_registro IS 'Fecha y hora del registro.';
CREATE INDEX ix_decision_clinica_id_usuario ON asistencia.decision_clinica (id_usuario);

-- ---------------------------------------------------------------------------
-- asistencia.reporte
-- ---------------------------------------------------------------------------
CREATE TABLE asistencia.reporte (
  id_reporte UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  numero_reporte VARCHAR(20) NOT NULL UNIQUE,
  id_consulta UUID NOT NULL REFERENCES asistencia.consulta (id_consulta),
  id_usuario UUID NOT NULL REFERENCES seguridad.usuario (id_usuario),
  destino VARCHAR(15) NOT NULL CHECK (destino IN ('EXPEDIENTE','CUIDADOR')),
  secciones_incluidas TEXT[] NOT NULL,
  formato VARCHAR(10) NOT NULL CHECK (formato IN ('PDF','IMPRESION')),
  hash_documento CHAR(64),
  fecha_generacion TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE asistencia.reporte IS 'Reporte exportado de una evaluación, destinado al expediente clínico o a la entrega al cuidador en lenguaje sencillo.';
COMMENT ON COLUMN asistencia.reporte.id_reporte IS 'Identificador del reporte.';
COMMENT ON COLUMN asistencia.reporte.numero_reporte IS 'Número correlativo visible (p. ej., EV-2026-00918).';
COMMENT ON COLUMN asistencia.reporte.id_consulta IS 'Consulta reportada.';
COMMENT ON COLUMN asistencia.reporte.id_usuario IS 'Profesional que genera el reporte.';
COMMENT ON COLUMN asistencia.reporte.destino IS 'EXPEDIENTE o CUIDADOR.';
COMMENT ON COLUMN asistencia.reporte.secciones_incluidas IS 'Secciones seleccionadas para el reporte.';
COMMENT ON COLUMN asistencia.reporte.formato IS 'PDF o IMPRESION.';
COMMENT ON COLUMN asistencia.reporte.hash_documento IS 'SHA-256 del documento emitido.';
COMMENT ON COLUMN asistencia.reporte.fecha_generacion IS 'Fecha y hora de emisión.';
CREATE INDEX ix_reporte_id_consulta ON asistencia.reporte (id_consulta);
CREATE INDEX ix_reporte_id_usuario ON asistencia.reporte (id_usuario);

-- ---------------------------------------------------------------------------
-- auditoria.evento_auditoria
-- ---------------------------------------------------------------------------
CREATE TABLE auditoria.evento_auditoria (
  id_evento BIGSERIAL PRIMARY KEY,
  id_usuario UUID REFERENCES seguridad.usuario (id_usuario),
  tipo_evento VARCHAR(40) NOT NULL,
  entidad VARCHAR(40),
  id_entidad VARCHAR(40),
  detalle JSONB,
  direccion_ip INET,
  fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE auditoria.evento_auditoria IS 'Bitácora de solo inserción de las acciones relevantes: inicios de sesión, accesos a la identidad del paciente, consultas procesadas, reportes exportados y cambios en guías, parámetros y usuarios. El rol de la aplicación no tiene permisos de modificación ni eliminación sobre esta tabla.';
COMMENT ON COLUMN auditoria.evento_auditoria.id_evento IS 'Identificador del evento.';
COMMENT ON COLUMN auditoria.evento_auditoria.id_usuario IS 'Usuario que ejecutó la acción (nulo en intentos de acceso con usuario inexistente).';
COMMENT ON COLUMN auditoria.evento_auditoria.tipo_evento IS 'Tipo de evento (p. ej., INICIO_SESION, CONSULTA_PROCESADA, PARAMETRO_MODIFICADO).';
COMMENT ON COLUMN auditoria.evento_auditoria.entidad IS 'Tabla afectada.';
COMMENT ON COLUMN auditoria.evento_auditoria.id_entidad IS 'Identificador del registro afectado.';
COMMENT ON COLUMN auditoria.evento_auditoria.detalle IS 'Valores anteriores y nuevos, sin datos identificatorios en claro.';
COMMENT ON COLUMN auditoria.evento_auditoria.direccion_ip IS 'Dirección IP de origen.';
COMMENT ON COLUMN auditoria.evento_auditoria.fecha_hora IS 'Fecha y hora del evento.';
CREATE INDEX ix_evento_auditoria_id_usuario ON auditoria.evento_auditoria (id_usuario);

-- ============================================================================
-- Reglas de integridad adicionales
-- ============================================================================
-- Un solo valor vigente por parámetro
CREATE UNIQUE INDEX ux_parametro_vigente ON configuracion.parametro_sistema (clave)
  WHERE vigente_hasta IS NULL;

-- Los rangos de edad vigentes de una misma categoría no se superponen
ALTER TABLE configuracion.umbral_hemoglobina ADD CONSTRAINT ex_umbral_sin_traslape
  EXCLUDE USING gist (id_categoria WITH =, int4range(edad_min_meses, edad_max_meses, '[]') WITH &&)
  WHERE (vigente_hasta IS NULL);

-- Los rangos de altitud vigentes no se superponen
ALTER TABLE configuracion.ajuste_altitud ADD CONSTRAINT ex_ajuste_sin_traslape
  EXCLUDE USING gist (int4range(altitud_min_msnm, altitud_max_msnm, '[]') WITH &&)
  WHERE (vigente_hasta IS NULL);

-- Índices de consulta frecuente
CREATE INDEX ix_tamizaje_paciente_fecha ON clinico.tamizaje (id_paciente, fecha_tamizaje DESC);
CREATE INDEX ix_consulta_estado_fecha ON asistencia.consulta (estado, fecha_hora_inicio DESC);
CREATE INDEX ix_documento_estado_nivel ON conocimiento.documento_fuente (estado, nivel);
CREATE INDEX ix_evento_fecha ON auditoria.evento_auditoria (fecha_hora DESC);

-- La recomendación solo puede registrarse para una consulta verificada
-- y con el intento aprobado de esa misma consulta
CREATE FUNCTION asistencia.fn_validar_recomendacion() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM asistencia.intento_generacion i
                 WHERE i.id_intento = NEW.id_intento
                   AND i.id_consulta = NEW.id_consulta
                   AND i.resultado = 'APROBADO') THEN
    RAISE EXCEPTION 'La recomendación debe provenir del intento aprobado de la misma consulta';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tg_validar_recomendacion BEFORE INSERT OR UPDATE ON asistencia.recomendacion
  FOR EACH ROW EXECUTE FUNCTION asistencia.fn_validar_recomendacion();

-- La cita debe referirse a un fragmento enviado al LLM en el intento de la recomendación
CREATE FUNCTION asistencia.fn_validar_cita() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM asistencia.recomendacion r
                 JOIN asistencia.fragmento_recuperado f
                   ON f.id_intento = r.id_intento
                 WHERE r.id_recomendacion = NEW.id_recomendacion
                   AND f.id_intento = NEW.id_intento
                   AND f.id_fragmento = NEW.id_fragmento
                   AND f.enviado_al_llm) THEN
    RAISE EXCEPTION 'La cita no corresponde a un fragmento enviado en el intento aprobado';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tg_validar_cita BEFORE INSERT OR UPDATE ON asistencia.cita_evidencia
  FOR EACH ROW EXECUTE FUNCTION asistencia.fn_validar_cita();

-- Bitácora de solo inserción
CREATE FUNCTION auditoria.fn_bloquear_cambios() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'La bitácora de auditoría no admite modificaciones ni eliminaciones';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER tg_bitacora_inmutable BEFORE UPDATE OR DELETE ON auditoria.evento_auditoria
  FOR EACH ROW EXECUTE FUNCTION auditoria.fn_bloquear_cambios();

-- ============================================================================
-- Vistas
-- ============================================================================
CREATE VIEW asistencia.v_historial_hemoglobina AS
SELECT t.id_paciente, t.id_tamizaje, t.fecha_tamizaje, t.edad_meses,
       t.hemoglobina_g_dl, r.hb_ajustada_g_dl, c.nombre AS clasificacion, r.nivel_riesgo
FROM clinico.tamizaje t
LEFT JOIN clinico.resultado_clasificacion r ON r.id_tamizaje = t.id_tamizaje
LEFT JOIN configuracion.categoria_anemia c ON c.id_categoria = r.id_categoria;

CREATE VIEW asistencia.v_auditoria_consulta AS
SELECT q.id_consulta, q.fecha_hora_inicio, u.nombre_usuario, q.estado, q.numero_intentos,
       q.latencia_total_ms, q.confirma_tamizaje_no_vigente, i.numero_intento, i.modelo_llm, i.tokens_entrada, i.tokens_salida,
       i.costo_usd, i.solicitud_enviada, i.valida_citas, i.valida_consistencia, i.valida_evidencia,
       i.resultado,
       (SELECT jsonb_agg(jsonb_build_object('etiqueta', f.etiqueta_cita,
                                            'puntaje', f.puntaje_reranker) ORDER BY f.posicion_final)
          FROM asistencia.fragmento_recuperado f
         WHERE f.id_intento = i.id_intento AND f.enviado_al_llm) AS fragmentos_enviados
FROM asistencia.consulta q
JOIN seguridad.usuario u ON u.id_usuario = q.id_usuario
LEFT JOIN asistencia.intento_generacion i ON i.id_consulta = q.id_consulta;

CREATE VIEW asistencia.v_indicadores_operativos AS
SELECT count(*) AS consultas,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY latencia_total_ms)
         FILTER (WHERE numero_intentos <= 1) AS p90_flujo_normal_ms,
       round(100.0 * count(*) FILTER (WHERE numero_intentos = 2) / NULLIF(count(*), 0), 1) AS pct_con_reintento,
       round(100.0 * count(*) FILTER (WHERE estado = 'EVIDENCIA_INSUFICIENTE') / NULLIF(count(*), 0), 1) AS pct_evidencia_insuficiente,
       (SELECT coalesce(sum(costo_usd), 0) FROM asistencia.intento_generacion
         WHERE fecha_hora >= now() - interval '30 days') AS costo_api_usd
FROM asistencia.consulta
WHERE fecha_hora_inicio >= now() - interval '30 days';

CREATE VIEW conocimiento.v_uso_documento AS
SELECT d.id_documento, d.titulo, d.nivel, d.estado, d.total_fragmentos,
       count(ce.id_cita) FILTER (WHERE r.fecha_generacion >= now() - interval '30 days') AS citas_30_dias
FROM conocimiento.documento_fuente d
LEFT JOIN conocimiento.fragmento f ON f.id_documento = d.id_documento
LEFT JOIN asistencia.cita_evidencia ce ON ce.id_fragmento = f.id_fragmento
LEFT JOIN asistencia.recomendacion r ON r.id_recomendacion = ce.id_recomendacion
GROUP BY d.id_documento;

CREATE VIEW asistencia.v_consultas_sin_evidencia AS
SELECT q.id_consulta, q.fecha_hora_inicio, i.consulta_reformulada, i.relevancia_maxima, i.umbral_relevancia
FROM asistencia.consulta q
JOIN asistencia.intento_generacion i ON i.id_consulta = q.id_consulta AND i.numero_intento = q.numero_intentos
WHERE q.estado = 'EVIDENCIA_INSUFICIENTE';

-- ============================================================================
-- Roles de base de datos (mínimo privilegio)
-- ============================================================================
DO $$
DECLARE r text;
BEGIN
  -- rol_app_clinica: registro de pacientes, tamizajes y re-vinculación (7.1)
  -- rol_app_generacion: recuperación, solicitud mínima (4.4) y verificación
  -- rol_app_admin: usuarios, guías y parámetros
  -- rol_auditor: solo lectura de auditoría e indicadores
  FOREACH r IN ARRAY ARRAY['rol_app_clinica','rol_app_generacion','rol_app_admin','rol_auditor'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;

GRANT USAGE ON SCHEMA seguridad, clinico, asistencia, conocimiento, configuracion, auditoria
  TO rol_app_clinica, rol_app_generacion, rol_app_admin, rol_auditor;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA clinico TO rol_app_clinica;
GRANT SELECT, INSERT, UPDATE ON asistencia.consulta, asistencia.dato_faltante,
      asistencia.decision_clinica, asistencia.reporte TO rol_app_clinica;
GRANT SELECT ON ALL TABLES IN SCHEMA configuracion, conocimiento TO rol_app_clinica;
GRANT SELECT ON asistencia.recomendacion, asistencia.cita_evidencia,
      asistencia.v_historial_hemoglobina TO rol_app_clinica;

-- El componente de generación no puede leer la identidad del paciente
GRANT SELECT ON clinico.paciente, clinico.tamizaje, clinico.tamizaje_sintoma, clinico.sintoma,
      clinico.resultado_clasificacion TO rol_app_generacion;
GRANT SELECT, UPDATE ON asistencia.consulta TO rol_app_generacion;
GRANT SELECT, INSERT, UPDATE ON asistencia.intento_generacion, asistencia.fragmento_recuperado,
      asistencia.recomendacion, asistencia.cita_evidencia TO rol_app_generacion;
GRANT SELECT ON ALL TABLES IN SCHEMA conocimiento, configuracion TO rol_app_generacion;
REVOKE ALL ON clinico.paciente_identidad FROM rol_app_generacion;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA seguridad, conocimiento, configuracion TO rol_app_admin;

GRANT SELECT ON ALL TABLES IN SCHEMA auditoria TO rol_auditor;
GRANT SELECT ON asistencia.v_auditoria_consulta, asistencia.v_indicadores_operativos TO rol_auditor;

GRANT INSERT ON auditoria.evento_auditoria TO rol_app_clinica, rol_app_generacion, rol_app_admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA seguridad, clinico, asistencia, conocimiento, configuracion, auditoria
  TO rol_app_clinica, rol_app_generacion, rol_app_admin;

-- ============================================================================
-- Datos iniciales de catálogos
-- ============================================================================
INSERT INTO seguridad.rol (nombre, descripcion) VALUES
  ('Enfermera CRED', 'Registra pacientes y tamizajes, realiza consultas y exporta reportes'),
  ('Médico', 'Realiza consultas clínicas y registra decisiones'),
  ('Nutricionista', 'Realiza consultas sobre consejería nutricional'),
  ('Coordinador CRED', 'Supervisa el servicio y configura parámetros clínicos'),
  ('Administrador', 'Administra usuarios, guías clínicas y parámetros del sistema');

INSERT INTO seguridad.permiso (codigo, descripcion) VALUES
  ('REGISTRAR_PACIENTE', 'Registrar y editar pacientes y tamizajes'),
  ('REALIZAR_CONSULTA', 'Formular consultas clínicas al sistema'),
  ('EXPORTAR_REPORTE', 'Exportar e imprimir reportes de evaluación'),
  ('CONFIGURAR_PARAMETROS', 'Modificar parámetros clínicos y de recuperación'),
  ('ADMINISTRAR_GUIAS', 'Cargar y retirar guías de la base de conocimiento'),
  ('ADMINISTRAR_USUARIOS', 'Crear, editar y desactivar cuentas'),
  ('VER_AUDITORIA', 'Consultar la bitácora y los indicadores operativos');

INSERT INTO configuracion.categoria_anemia (nombre, nivel_riesgo, requiere_derivacion, orden) VALUES
  ('SIN_ANEMIA', 'BAJO', false, 1),
  ('ANEMIA_LEVE', 'MODERADO', false, 2),
  ('ANEMIA_MODERADA', 'ALTO', false, 3),
  ('ANEMIA_SEVERA', 'MUY_ALTO', true, 4);

INSERT INTO clinico.sintoma (nombre) VALUES
  ('Palidez'), ('Hiporexia'), ('Irritabilidad'), ('Fatiga o somnolencia'),
  ('Retraso del desarrollo'), ('Otro');
