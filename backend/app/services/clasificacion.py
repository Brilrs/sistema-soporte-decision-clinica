"""2.3 · Cálculo clínico determinístico.

Ajusta la hemoglobina por la altitud de residencia y la clasifica con los puntos
de corte vigentes. No hay valores clínicos en el código: el ajuste, los puntos de
corte y las categorías se leen de configuracion.ajuste_altitud,
configuracion.umbral_hemoglobina y configuracion.categoria_anemia, que la
coordinación CRED mantiene desde M12."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

_UN_DECIMAL = Decimal("0.1")


@dataclass(frozen=True)
class Clasificacion:
    altitud_msnm: int
    id_ajuste: int
    ajuste_hb_g_dl: Decimal
    hb_ajustada_g_dl: Decimal
    id_umbral: int
    id_categoria: int
    categoria: str
    nivel_riesgo: str
    requiere_derivacion: bool


@dataclass(frozen=True)
class Evaluacion:
    """Resultado del cálculo: la clasificación o el motivo por el que no se pudo clasificar."""
    clasificacion: Clasificacion | None
    motivo: str | None = None


def rango_edad_clasificable(sesion: Session | Connection) -> tuple[int, int] | None:
    """Edades (en meses) cubiertas por los puntos de corte vigentes."""
    fila = sesion.execute(text("""SELECT min(edad_min_meses), max(edad_max_meses)
                                    FROM configuracion.umbral_hemoglobina
                                   WHERE vigente_hasta IS NULL""")).first()
    return None if fila is None or fila[0] is None else (fila[0], fila[1])


def motivo_fuera_de_rango(rango: tuple[int, int] | None) -> str:
    if rango is None:
        return "No hay puntos de corte de hemoglobina vigentes"
    return f"Fuera del rango de edad de los puntos de corte ({rango[0]} a {rango[1]} meses)"


def clasificar(sesion: Session | Connection, hemoglobina_g_dl: Decimal | None,
               edad_meses: int, altitud_msnm: int) -> Evaluacion:
    if hemoglobina_g_dl is None:
        return Evaluacion(None, "Falta la hemoglobina")

    ajuste = sesion.execute(
        text("""SELECT id_ajuste, ajuste_g_dl FROM configuracion.ajuste_altitud
                 WHERE vigente_hasta IS NULL AND :alt BETWEEN altitud_min_msnm AND altitud_max_msnm"""),
        {"alt": altitud_msnm},
    ).first()
    if ajuste is None:
        return Evaluacion(None, f"No hay ajuste por altitud vigente para {altitud_msnm} m.s.n.m.")

    hb_ajustada = (Decimal(hemoglobina_g_dl) - ajuste.ajuste_g_dl).quantize(_UN_DECIMAL, ROUND_HALF_UP)

    umbral = sesion.execute(
        text("""SELECT u.id_umbral, c.id_categoria, c.nombre, c.nivel_riesgo, c.requiere_derivacion
                  FROM configuracion.umbral_hemoglobina u
                  JOIN configuracion.categoria_anemia c ON c.id_categoria = u.id_categoria
                 WHERE u.vigente_hasta IS NULL
                   AND :edad BETWEEN u.edad_min_meses AND u.edad_max_meses
                   AND (u.hb_min_g_dl IS NULL OR :hb >= u.hb_min_g_dl)
                   AND (u.hb_max_g_dl IS NULL OR :hb <= u.hb_max_g_dl)
                 ORDER BY c.orden DESC
                 LIMIT 1"""),
        {"edad": edad_meses, "hb": hb_ajustada},
    ).first()
    if umbral is None:
        rango = rango_edad_clasificable(sesion)
        if rango is None or not rango[0] <= edad_meses <= rango[1]:
            return Evaluacion(None, motivo_fuera_de_rango(rango))
        return Evaluacion(None, f"La hemoglobina ajustada ({hb_ajustada} g/dL) no coincide con ningún punto de corte vigente")

    return Evaluacion(Clasificacion(
        altitud_msnm=altitud_msnm,
        id_ajuste=ajuste.id_ajuste,
        ajuste_hb_g_dl=ajuste.ajuste_g_dl,
        hb_ajustada_g_dl=hb_ajustada,
        id_umbral=umbral.id_umbral,
        id_categoria=umbral.id_categoria,
        categoria=umbral.nombre,
        nivel_riesgo=umbral.nivel_riesgo,
        requiere_derivacion=umbral.requiere_derivacion,
    ))


def guardar_resultado(sesion: Session | Connection, id_tamizaje: str, c: Clasificacion) -> None:
    """Guarda la instantánea de los valores aplicados, para que el resultado no cambie
    si luego se modifican los parámetros o el distrito del paciente."""
    sesion.execute(
        text("""INSERT INTO clinico.resultado_clasificacion
                  (id_tamizaje, altitud_msnm, id_ajuste, ajuste_hb_g_dl, hb_ajustada_g_dl,
                   id_umbral, id_categoria, nivel_riesgo)
                VALUES (CAST(:t AS uuid), :alt, :aj, :ajv, :hba, :um, :cat, :riesgo)"""),
        {"t": id_tamizaje, "alt": c.altitud_msnm, "aj": c.id_ajuste, "ajv": c.ajuste_hb_g_dl,
         "hba": c.hb_ajustada_g_dl, "um": c.id_umbral, "cat": c.id_categoria, "riesgo": c.nivel_riesgo},
    )
