"""HU02 Registrar paciente · HU04 Actualizar y consultar la información del paciente ·
HU05 Registrar síntomas y antecedentes · HU18 Registrar nuevo tamizaje
(pantallas M02, M03, M08 y M14)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import UsuarioActual, requiere_algun_permiso, requiere_permiso
from app.core.auditoria import registrar_evento
from app.core.db import sesion_clinica
from app.core.fechas import edad_en_meses, hoy
from app.services import pacientes as srv
from app.services.clasificacion import Evaluacion

router = APIRouter(prefix="/api/pacientes", tags=["Pacientes"])

# Lectura: quien registra pacientes o realiza consultas (enfermera, médico,
# nutricionista y coordinación). Escritura: solo REGISTRAR_PACIENTE.
lectura = requiere_algun_permiso("REGISTRAR_PACIENTE", "REALIZAR_CONSULTA")
escritura = requiere_permiso("REGISTRAR_PACIENTE")

MENSAJE_NO_ENCONTRADO = "El paciente no existe"
# Datos que no cumplen una regla del negocio (el nombre de la constante cambia entre versiones de Starlette)
DATOS_NO_VALIDOS = 422


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------
class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Busqueda(_Entrada):
    texto: str = Field(min_length=1, max_length=150, description="DNI, N.° de historia clínica o nombre")


class SintomaEntrada(_Entrada):
    id_sintoma: int
    detalle: str | None = Field(None, max_length=150)


class TamizajeEntrada(_Entrada):
    fecha_tamizaje: date
    hemoglobina_g_dl: Decimal | None = Field(None, ge=Decimal("3.0"), le=Decimal("20.0"), decimal_places=1)
    metodo_medicion: Literal["HEMOGLOBINOMETRO", "LABORATORIO"] | None = None
    # Límites de captura amplios (no son valores clínicos): evitan errores de digitación
    peso_kg: Decimal | None = Field(None, gt=0, le=60, decimal_places=2)
    talla_cm: Decimal | None = Field(None, gt=0, le=150, decimal_places=1)
    recibe_suplementacion_hierro: bool | None = None
    lactancia_materna_actual: bool | None = None
    parasitosis_reciente: bool | None = None
    observaciones: str | None = Field(None, max_length=2000)
    sintomas: list[SintomaEntrada] = Field(default_factory=list)

    def a_datos(self) -> srv.DatosTamizaje:
        return srv.DatosTamizaje(
            fecha_tamizaje=self.fecha_tamizaje, hemoglobina_g_dl=self.hemoglobina_g_dl,
            metodo_medicion=self.metodo_medicion, peso_kg=self.peso_kg, talla_cm=self.talla_cm,
            recibe_suplementacion_hierro=self.recibe_suplementacion_hierro,
            lactancia_materna_actual=self.lactancia_materna_actual,
            parasitosis_reciente=self.parasitosis_reciente, observaciones=self.observaciones or None,
            sintomas=[(s.id_sintoma, s.detalle) for s in self.sintomas])


class _Identidad(_Entrada):
    @field_validator("dni", check_fields=False)
    @classmethod
    def _dni(cls, v: str | None) -> str | None:
        if v is not None and not (len(v) == 8 and v.isdigit()):
            raise ValueError("El DNI debe tener 8 dígitos")
        return v


class PacienteEntrada(_Identidad):
    nombres_apellidos: str = Field(min_length=3, max_length=150)
    dni: str
    numero_hc: str = Field(min_length=1, max_length=20)
    direccion: str | None = Field(None, max_length=250)
    ubigeo_residencia: str = Field(pattern=r"^\d{6}$")
    fecha_nacimiento: date
    sexo: Literal["M", "F"]
    edad_gestacional_nacer: Literal["A_TERMINO", "PRETERMINO", "NO_REGISTRADO"] = "NO_REGISTRADO"
    bajo_peso_nacer: bool | None = None
    tamizaje: TamizajeEntrada | None = None


class PacienteCambios(_Identidad):
    """Solo se modifican los campos enviados."""
    nombres_apellidos: str | None = Field(None, min_length=3, max_length=150)
    dni: str | None = None
    numero_hc: str | None = Field(None, min_length=1, max_length=20)
    direccion: str | None = Field(None, max_length=250)
    ubigeo_residencia: str | None = Field(None, pattern=r"^\d{6}$")
    fecha_nacimiento: date | None = None
    sexo: Literal["M", "F"] | None = None
    edad_gestacional_nacer: Literal["A_TERMINO", "PRETERMINO", "NO_REGISTRADO"] | None = None
    bajo_peso_nacer: bool | None = None

    @field_validator("nombres_apellidos", "dni", "numero_hc", "ubigeo_residencia", "fecha_nacimiento", "sexo",
                     "edad_gestacional_nacer")
    @classmethod
    def _obligatorio(cls, v):
        if v is None:
            raise ValueError("no puede quedar vacío")
        return v


# ---------------------------------------------------------------------------
# Modelos de salida
# ---------------------------------------------------------------------------
class ClasificacionSalida(BaseModel):
    categoria: str
    nivel_riesgo: str
    requiere_derivacion: bool
    altitud_msnm: int
    ajuste_hb_g_dl: Decimal
    hb_ajustada_g_dl: Decimal


class EvaluacionSalida(BaseModel):
    edad_meses: int
    clasificacion: ClasificacionSalida | None
    motivo_sin_clasificacion: str | None


class TamizajeRegistrado(EvaluacionSalida):
    id_tamizaje: str


class PacienteRegistrado(BaseModel):
    id_paciente: str
    tamizaje: TamizajeRegistrado | None


class UltimoTamizaje(BaseModel):
    fecha_tamizaje: date
    fecha_registro: datetime
    hemoglobina_g_dl: Decimal | None
    hb_ajustada_g_dl: Decimal | None
    categoria: str | None
    nivel_riesgo: str | None
    vigente: bool


class PacienteListado(BaseModel):
    id_paciente: str
    nombres_apellidos: str
    numero_hc: str
    sexo: str
    edad_meses_actual: int
    ultimo_tamizaje: UltimoTamizaje | None


class Indicadores(BaseModel):
    """Los valores nulos se muestran como «Sin datos» (dependen de las consultas del Sprint 2)."""
    evaluaciones_hoy: int | None
    con_anemia_detectada: int
    controles_pendientes: int
    tiempo_medio_respuesta_s: float | None
    dias_vigencia_tamizaje: int


class Ficha(BaseModel):
    id_paciente: str
    nombres_apellidos: str
    dni: str
    numero_hc: str
    direccion: str | None
    fecha_nacimiento: date
    edad_meses_actual: int
    sexo: str
    ubigeo_residencia: str
    distrito: str
    provincia: str
    departamento: str
    altitud_msnm: int
    edad_gestacional_nacer: str
    bajo_peso_nacer: bool | None
    registrado_por: str
    fecha_registro: datetime


class SintomaSalida(BaseModel):
    id_sintoma: int
    nombre: str
    detalle: str | None


class TamizajeHistorial(BaseModel):
    id_tamizaje: str
    fecha_tamizaje: date
    fecha_registro: datetime
    edad_meses: int
    hemoglobina_g_dl: Decimal | None
    metodo_medicion: str | None
    peso_kg: Decimal | None
    talla_cm: Decimal | None
    recibe_suplementacion_hierro: bool | None
    lactancia_materna_actual: bool | None
    parasitosis_reciente: bool | None
    observaciones: str | None
    profesional: str
    sintomas: list[SintomaSalida]
    vigente: bool
    clasificacion: ClasificacionSalida | None
    motivo_sin_clasificacion: str | None


class Franja(BaseModel):
    edad_min_meses: int
    edad_max_meses: int
    categoria: str
    nivel_riesgo: str
    hb_min_g_dl: Decimal | None
    hb_max_g_dl: Decimal | None


class Historial(BaseModel):
    id_paciente: str
    tamizajes: list[TamizajeHistorial]
    franjas: list[Franja]
    consultas: list[dict] = Field(default_factory=list, description="Evaluaciones RAG (Sprint 2)")


class VistaPrevia(EvaluacionSalida):
    anterior: TamizajeHistorial | None


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _evaluacion_salida(edad: int, ev: Evaluacion) -> dict:
    c = ev.clasificacion
    return {
        "edad_meses": edad,
        "clasificacion": None if c is None else {
            "categoria": c.categoria, "nivel_riesgo": c.nivel_riesgo, "requiere_derivacion": c.requiere_derivacion,
            "altitud_msnm": c.altitud_msnm, "ajuste_hb_g_dl": c.ajuste_hb_g_dl, "hb_ajustada_g_dl": c.hb_ajustada_g_dl},
        "motivo_sin_clasificacion": ev.motivo,
    }


def _detalle_tamizaje(id_paciente: str, ev: Evaluacion) -> dict:
    """Detalle de auditoría del tamizaje: sin identificadores del paciente."""
    c = ev.clasificacion
    return {"id_paciente": id_paciente, "categoria": c.categoria if c else None,
            "nivel_riesgo": c.nivel_riesgo if c else None}


def _paciente_o_404(sesion: Session, id_paciente: UUID):
    paciente = srv.datos_permanentes(sesion, str(id_paciente))
    if paciente is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADO)
    return paciente


def _error_negocio(exc: Exception) -> HTTPException:
    if isinstance(exc, srv.ErrorDuplicado):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(DATOS_NO_VALIDOS, str(exc))


# ---------------------------------------------------------------------------
# Panel y búsqueda (M02)
# ---------------------------------------------------------------------------
@router.get("", response_model=list[PacienteListado])
def recientes(_: UsuarioActual = Depends(lectura), sesion: Session = Depends(sesion_clinica)) -> list[dict]:
    """Pacientes atendidos recientemente."""
    return srv.recientes(sesion)


@router.post("/buscar", response_model=list[PacienteListado])
def buscar(datos: Busqueda, request: Request, usuario: UsuarioActual = Depends(lectura),
           sesion: Session = Depends(sesion_clinica)) -> list[dict]:
    """El texto va en el cuerpo y no en la URL, para que el DNI o el nombre no queden en los
    registros de acceso de Nginx ni del servidor. La auditoría guarda solo el tipo de
    coincidencia y el número de resultados, nunca el texto buscado."""
    encontrados, coincidencias = srv.buscar(sesion, datos.texto)
    registrar_evento(sesion, "PACIENTE_BUSCADO", usuario.id_usuario, "paciente", None,
                     {"coincidencias": coincidencias, "resultados": len(encontrados)}, _ip(request))
    sesion.commit()
    return encontrados


@router.get("/indicadores", response_model=Indicadores)
def ver_indicadores(_: UsuarioActual = Depends(lectura), sesion: Session = Depends(sesion_clinica)) -> dict:
    return srv.indicadores(sesion)


# ---------------------------------------------------------------------------
# Registro (M03)
# ---------------------------------------------------------------------------
@router.post("", response_model=PacienteRegistrado, status_code=status.HTTP_201_CREATED)
def registrar(datos: PacienteEntrada, request: Request, usuario: UsuarioActual = Depends(escritura),
              sesion: Session = Depends(sesion_clinica)) -> dict:
    try:
        id_paciente = srv.registrar_paciente(
            sesion, usuario.id_usuario, nombres_apellidos=datos.nombres_apellidos, dni=datos.dni,
            numero_hc=datos.numero_hc, direccion=datos.direccion or None, ubigeo_residencia=datos.ubigeo_residencia,
            fecha_nacimiento=datos.fecha_nacimiento, sexo=datos.sexo,
            edad_gestacional_nacer=datos.edad_gestacional_nacer, bajo_peso_nacer=datos.bajo_peso_nacer)
        tamizaje = None
        if datos.tamizaje is not None:
            paciente = srv.datos_permanentes(sesion, id_paciente)
            id_tamizaje, edad, ev = srv.registrar_tamizaje(sesion, usuario.id_usuario, paciente, datos.tamizaje.a_datos())
            tamizaje = {"id_tamizaje": id_tamizaje, **_evaluacion_salida(edad, ev)}
        elif not 0 <= edad_en_meses(datos.fecha_nacimiento, hoy()) <= 59:
            raise srv.ErrorDatos("El sistema atiende a niños de 0 a 59 meses")
    except (srv.ErrorDatos, srv.ErrorDuplicado) as exc:
        sesion.rollback()
        raise _error_negocio(exc)
    except IntegrityError:
        # Otro registro con el mismo DNI o historia clínica se guardó al mismo tiempo
        sesion.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un paciente registrado con ese DNI o historia clínica")

    registrar_evento(sesion, "PACIENTE_REGISTRADO", usuario.id_usuario, "paciente", id_paciente,
                     {"con_tamizaje": tamizaje is not None}, _ip(request))
    if tamizaje is not None:
        registrar_evento(sesion, "TAMIZAJE_REGISTRADO", usuario.id_usuario, "tamizaje", tamizaje["id_tamizaje"],
                         _detalle_tamizaje(id_paciente, ev), _ip(request))
    sesion.commit()
    return {"id_paciente": id_paciente, "tamizaje": tamizaje}


# ---------------------------------------------------------------------------
# Ficha y corrección de datos (HU04)
# ---------------------------------------------------------------------------
@router.get("/{id_paciente}", response_model=Ficha)
def ver_ficha(id_paciente: UUID, request: Request, usuario: UsuarioActual = Depends(lectura),
              sesion: Session = Depends(sesion_clinica)) -> dict:
    datos = srv.ficha(sesion, str(id_paciente))
    if datos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MENSAJE_NO_ENCONTRADO)
    registrar_evento(sesion, "IDENTIDAD_CONSULTADA", usuario.id_usuario, "paciente_identidad", str(id_paciente),
                     None, _ip(request))
    sesion.commit()
    return datos


@router.patch("/{id_paciente}", response_model=Ficha)
def actualizar(id_paciente: UUID, cambios: PacienteCambios, request: Request,
               usuario: UsuarioActual = Depends(escritura), sesion: Session = Depends(sesion_clinica)) -> dict:
    _paciente_o_404(sesion, id_paciente)
    enviados = cambios.model_dump(include=cambios.model_fields_set)
    if "direccion" in enviados and not enviados["direccion"]:
        enviados["direccion"] = None
    if not enviados:
        raise HTTPException(DATOS_NO_VALIDOS, "No se envió ningún dato para actualizar")
    try:
        campos = srv.actualizar_paciente(sesion, str(id_paciente), enviados)
    except (srv.ErrorDatos, srv.ErrorDuplicado) as exc:
        sesion.rollback()
        raise _error_negocio(exc)
    except IntegrityError:
        sesion.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un paciente registrado con ese DNI o historia clínica")
    # Solo los nombres de los campos: los valores pueden ser identificatorios
    registrar_evento(sesion, "PACIENTE_ACTUALIZADO", usuario.id_usuario, "paciente", str(id_paciente),
                     {"campos": campos}, _ip(request))
    sesion.commit()
    return srv.ficha(sesion, str(id_paciente))


# ---------------------------------------------------------------------------
# Tamizajes (M14) e historial (M08)
# ---------------------------------------------------------------------------
@router.post("/{id_paciente}/tamizajes", response_model=TamizajeRegistrado, status_code=status.HTTP_201_CREATED)
def nuevo_tamizaje(id_paciente: UUID, datos: TamizajeEntrada, request: Request,
                   usuario: UsuarioActual = Depends(escritura), sesion: Session = Depends(sesion_clinica)) -> dict:
    paciente = _paciente_o_404(sesion, id_paciente)
    try:
        id_tamizaje, edad, ev = srv.registrar_tamizaje(sesion, usuario.id_usuario, paciente, datos.a_datos())
    except srv.ErrorDatos as exc:
        sesion.rollback()
        raise _error_negocio(exc)
    registrar_evento(sesion, "TAMIZAJE_REGISTRADO", usuario.id_usuario, "tamizaje", id_tamizaje,
                     _detalle_tamizaje(str(id_paciente), ev), _ip(request))
    sesion.commit()
    return {"id_tamizaje": id_tamizaje, **_evaluacion_salida(edad, ev)}


@router.post("/{id_paciente}/tamizajes/vista-previa", response_model=VistaPrevia)
def vista_previa(id_paciente: UUID, datos: TamizajeEntrada, _: UsuarioActual = Depends(escritura),
                 sesion: Session = Depends(sesion_clinica)) -> dict:
    """Calcula la clasificación sin guardar nada y la compara con el control anterior."""
    paciente = _paciente_o_404(sesion, id_paciente)
    try:
        edad, ev = srv.evaluar_tamizaje(sesion, paciente, datos.a_datos())
    except srv.ErrorDatos as exc:
        raise _error_negocio(exc)
    anteriores = srv.historial(sesion, str(id_paciente))
    return {**_evaluacion_salida(edad, ev), "anterior": anteriores[0] if anteriores else None}


@router.get("/{id_paciente}/historial", response_model=Historial)
def ver_historial(id_paciente: UUID, _: UsuarioActual = Depends(lectura),
                  sesion: Session = Depends(sesion_clinica)) -> dict:
    """Sin datos de identidad: el encabezado de M08 los toma de la ficha."""
    _paciente_o_404(sesion, id_paciente)
    return {"id_paciente": str(id_paciente), "tamizajes": srv.historial(sesion, str(id_paciente)),
            "franjas": srv.franjas_vigentes(sesion), "consultas": []}
