"""M07 mínimo: «Registrar decisión clínica» sobre una consulta terminada, con la sesión de
cdss_clinica y la tabla asistencia.decision_clinica (una decisión por consulta).

Reglas (aprobadas en D2):
- VERIFICADA admite los tres tipos; EVIDENCIA_INSUFICIENTE y ERROR, solo
  CRITERIO_CLINICO_PROPIO; los demás estados no admiten decisión.
- La nota (columna descripcion) es opcional, hasta 1000 caracteres, y obligatoria con
  MODIFICA_RECOMENDACION.
- opciones_decision(estado) es la fuente única de estas reglas: la API la devuelve en el
  evento final y en el resultado de la consulta para que la interfaz no las duplique.
- La auditoría guarda el tipo y si hay nota, nunca el texto de la nota."""
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ACEPTA_RECOMENDACION = "ACEPTA_RECOMENDACION"
MODIFICA_RECOMENDACION = "MODIFICA_RECOMENDACION"
CRITERIO_CLINICO_PROPIO = "CRITERIO_CLINICO_PROPIO"
TIPOS = (ACEPTA_RECOMENDACION, MODIFICA_RECOMENDACION, CRITERIO_CLINICO_PROPIO)
NOTA_OBLIGATORIA = frozenset({MODIFICA_RECOMENDACION})
LARGO_MAXIMO_NOTA = 1000
TIPOS_POR_ESTADO = {
    "VERIFICADA": TIPOS,
    "EVIDENCIA_INSUFICIENTE": (CRITERIO_CLINICO_PROPIO,),
    "ERROR": (CRITERIO_CLINICO_PROPIO,),
}


class ErrorDecision(Exception):
    """La decisión no se puede registrar en el estado actual (409) o le falta la nota (422)."""

    def __init__(self, mensaje: str, codigo: int):
        super().__init__(mensaje)
        self.codigo = codigo


def opciones_decision(estado: str | None) -> list[dict]:
    return [{"tipo": t, "nota_obligatoria": t in NOTA_OBLIGATORIA} for t in TIPOS_POR_ESTADO.get(estado or "", ())]


def leer_decision(sesion: Session | Connection, id_consulta: str) -> dict | None:
    fila = sesion.execute(text(
        """SELECT id_decision::text, id_usuario::text, tipo_decision, descripcion, fecha_registro
             FROM asistencia.decision_clinica WHERE id_consulta = CAST(:c AS uuid)"""), {"c": id_consulta}).first()
    if fila is None:
        return None
    return {"id_decision": fila.id_decision, "id_usuario": fila.id_usuario, "tipo_decision": fila.tipo_decision,
            "nota": fila.descripcion, "fecha_registro": fila.fecha_registro}


def registrar_decision(sesion: Session | Connection, id_consulta: str, estado: str, id_usuario: str, tipo: str,
                       nota: str | None) -> dict:
    permitidos = TIPOS_POR_ESTADO.get(estado, ())
    if not permitidos:
        raise ErrorDecision(f"Una consulta en estado {estado} no admite una decisión clínica", 409)
    if tipo not in permitidos:
        raise ErrorDecision(f"En una consulta {estado} solo se admite: {', '.join(permitidos)}", 409)
    nota = (nota or "").strip() or None
    if tipo in NOTA_OBLIGATORIA and nota is None:
        raise ErrorDecision(f"La nota es obligatoria con {tipo}", 422)
    if leer_decision(sesion, id_consulta) is not None:
        raise ErrorDecision("La consulta ya tiene una decisión registrada", 409)
    try:
        sesion.execute(text(
            """INSERT INTO asistencia.decision_clinica (id_consulta, id_usuario, tipo_decision, descripcion)
               VALUES (CAST(:c AS uuid), CAST(:u AS uuid), :t, :d)"""),
            {"c": id_consulta, "u": id_usuario, "t": tipo, "d": nota})
    except IntegrityError as e:
        raise ErrorDecision("La consulta ya tiene una decisión registrada", 409) from e
    return leer_decision(sesion, id_consulta)
