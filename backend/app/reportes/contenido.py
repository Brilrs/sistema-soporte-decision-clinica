"""Contenido estructurado del reporte exportable (M09, HU10; Sprint 3, parte C1).

El mismo contenido sirve para la vista previa (JSON) y para el PDF: una lista de bloques, cada uno
con su sección, título, campos (etiqueta y valor), párrafos e ítems. Nada de esto llama al modelo
de lenguaje:
- EXPEDIENTE copia lo que ya está guardado en la consulta (clasificación, recomendación verificada,
  citas, advertencias, verificación y decisión).
- CUIDADOR usa solo las frases fijas de lenguaje_sencillo.yaml, elegidas por la clasificación, la
  derivación y el tipo de cada paso; nunca el texto generado.

Del paciente solo se muestran el nombre y la historia clínica (descifrados con cdss_clinica, como en
M02), el sexo y la edad; nunca el DNI ni la dirección."""
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.core.fechas import ZONA_PERU
from app.services import resultados as res
from app.services.pacientes import nombres_e_historias

ARCHIVO_FRASES = Path(__file__).with_name("lenguaje_sencillo.yaml")

EXPEDIENTE, CUIDADOR = "EXPEDIENTE", "CUIDADOR"
DESTINOS = (EXPEDIENTE, CUIDADOR)
ESTADOS_CON_RESULTADO = ("VERIFICADA", "EVIDENCIA_INSUFICIENTE")

TITULOS = {
    "PACIENTE": "Datos del paciente",
    "CLASIFICACION": "Clasificación y nivel de riesgo",
    "RECOMENDACION": "Recomendación clínica",
    "EVIDENCIAS": "Evidencias citadas",
    "ADVERTENCIAS": "Advertencias",
    "VERIFICACION": "Verificación de la respuesta",
    "DECISION": "Decisión del profesional",
    "FIRMA": "Firma y sello",
}
# Secciones admitidas por destino, en el orden del reporte. Las obligatorias van siempre.
SECCIONES_POR_DESTINO = {
    EXPEDIENTE: ("PACIENTE", "CLASIFICACION", "RECOMENDACION", "EVIDENCIAS", "ADVERTENCIAS", "VERIFICACION",
                 "DECISION", "FIRMA"),
    CUIDADOR: ("PACIENTE", "CLASIFICACION", "RECOMENDACION", "FIRMA"),
}
OBLIGATORIAS = ("PACIENTE", "CLASIFICACION")

FRASE_FINAL = "La decisión final corresponde al profesional tratante."
AVISO_PRUEBA = "MODO DE PRUEBA, no es un documento clínico"
AVISO_REVISION = "Texto en revisión clínica: no entregar a pacientes"
TITULO_EXPEDIENTE = "Reporte de evaluación de anemia infantil"

CATEGORIAS = {"SIN_ANEMIA": "Sin anemia", "ANEMIA_LEVE": "Anemia leve", "ANEMIA_MODERADA": "Anemia moderada",
              "ANEMIA_SEVERA": "Anemia severa"}
NIVELES = {"BAJO": "Bajo", "MODERADO": "Moderado", "ALTO": "Alto", "MUY_ALTO": "Muy alto"}
SEXOS = {"M": "Masculino", "F": "Femenino"}
TIPOS_PASO = {"PREVENCION": "Prevención", "TRATAMIENTO": "Tratamiento", "DERIVACION": "Derivación",
              "SEGUIMIENTO": "Seguimiento", "CONSEJERIA": "Consejería", "OTRO": "Otro"}
TIPOS_DECISION = {"ACEPTA_RECOMENDACION": "Acepta la recomendación",
                  "MODIFICA_RECOMENDACION": "Modifica la recomendación",
                  "CRITERIO_CLINICO_PROPIO": "Criterio clínico propio"}
ESTADOS = {"VERIFICADA": "Verificada", "EVIDENCIA_INSUFICIENTE": "Evidencia insuficiente"}


class SeccionInvalida(ValueError):
    """Sección desconocida o no admitida para el destino (se responde con 422)."""


@lru_cache
def frases() -> dict:
    """Frases fijas del reporte para el cuidador (se leen una vez por proceso)."""
    return yaml.safe_load(ARCHIVO_FRASES.read_text(encoding="utf-8"))


def secciones_finales(destino: str, elegidas: list[str]) -> list[str]:
    """Las obligatorias más las elegidas, sin repetir y en el orden del reporte."""
    admitidas = SECCIONES_POR_DESTINO[destino]
    for s in elegidas:
        if s not in TITULOS:
            raise SeccionInvalida(f"sección desconocida: {s}")
        if s not in admitidas:
            raise SeccionInvalida(f"la sección {s} no se admite en el reporte {destino}")
    pedidas = set(elegidas) | set(OBLIGATORIAS)
    return [s for s in admitidas if s in pedidas]


# ---------------------------------------------------------------------------
# Datos de la consulta
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DatosReporte:
    clinico: dict          # resultados.parte_clinica (cdss_clinica)
    generacion: dict       # resultados.parte_generacion (cdss_generacion)
    nombres_apellidos: str
    numero_hc: str
    sexo: str | None
    fecha_tamizaje: date
    edad_meses: int
    hemoglobina_g_dl: float | None

    @property
    def modo_prueba(self) -> bool:
        return bool(self.generacion["modo_prueba"])


def leer_datos(clinica: Session | Connection, generacion: Session | Connection, f: res.FichaConsulta) -> DatosReporte:
    clinico = res.parte_clinica(clinica, f)
    gen = res.parte_generacion(generacion, f.id_consulta)
    identidad = nombres_e_historias(clinica, [f.id_paciente])[f.id_paciente]
    t = clinica.execute(text(
        """SELECT p.sexo, t.fecha_tamizaje, t.edad_meses, t.hemoglobina_g_dl
             FROM clinico.tamizaje t JOIN clinico.paciente p ON p.id_paciente = t.id_paciente
            WHERE t.id_tamizaje = CAST(:t AS uuid)"""), {"t": f.id_tamizaje}).one()
    return DatosReporte(clinico, gen, identidad["nombres_apellidos"], identidad["numero_hc"], t.sexo,
                        t.fecha_tamizaje, t.edad_meses, None if t.hemoglobina_g_dl is None else float(t.hemoglobina_g_dl))


# ---------------------------------------------------------------------------
# Formato
# ---------------------------------------------------------------------------
def fecha_hora(valor: datetime) -> str:
    return valor.astimezone(ZONA_PERU).strftime("%d/%m/%Y %H:%M")


def fecha(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def _hb(valor: float | None) -> str:
    return "Sin dato" if valor is None else f"{valor:.1f} g/dL"


def _edad(meses: int) -> str:
    return f"{meses} {'mes' if meses == 1 else 'meses'}"


def _control(valor: bool | None) -> str:
    return "No evaluado" if valor is None else "Cumplido" if valor else "No cumplido"


def _paginas(inicio: int | None, fin: int | None) -> str | None:
    if inicio is None:
        return None
    return f"Página {inicio}" if fin in (None, inicio) else f"Páginas {inicio} a {fin}"


def _bloque(seccion: str, titulo: str | None = None, *, campos=None, parrafos=None, items=None) -> dict:
    return {"seccion": seccion, "titulo": titulo or TITULOS.get(seccion, seccion), "campos": campos or [],
            "parrafos": parrafos or [], "items": items or []}


def _campo(etiqueta: str, valor: str) -> dict:
    return {"etiqueta": etiqueta, "valor": valor}


# ---------------------------------------------------------------------------
# Bloques del expediente
# ---------------------------------------------------------------------------
def _paciente(d: DatosReporte) -> dict:
    c = d.clinico["clasificacion"]
    campos = [_campo("Paciente", d.nombres_apellidos), _campo("Historia clínica", d.numero_hc),
              _campo("Sexo", SEXOS.get(d.sexo or "", "No registrado")),
              _campo("Edad al tamizaje", _edad(d.edad_meses)),
              _campo("Fecha del tamizaje", fecha(d.fecha_tamizaje)),
              _campo("Fecha de la consulta", fecha_hora(d.clinico["fecha_hora_inicio"])),
              _campo("Hb observada", _hb(d.hemoglobina_g_dl))]
    if c is not None:
        campos += [_campo("Hb ajustada por altitud", _hb(c["hb_ajustada_g_dl"])),
                   _campo("Altitud", "Sin dato" if c["altitud_msnm"] is None else f"{c['altitud_msnm']} m.s.n.m.")]
    return _bloque("PACIENTE", campos=campos)


def _clasificacion(d: DatosReporte) -> dict:
    c = d.clinico["clasificacion"]
    if c is None:
        return _bloque("CLASIFICACION", parrafos=["La evaluación no tiene clasificación de anemia."])
    reco = d.generacion["recomendacion"] or {}
    factores = reco.get("factores_identificados") or []
    return _bloque("CLASIFICACION", campos=[
        _campo("Clasificación", CATEGORIAS.get(c["categoria"], c["categoria"])),
        _campo("Nivel de riesgo", NIVELES.get(c["nivel_riesgo"], c["nivel_riesgo"])),
        _campo("Requiere derivación", "Sí" if c["requiere_derivacion"] else "No"),
        _campo("Factores identificados", "; ".join(factores) if factores else "Sin factores adicionales"),
    ])


def _recomendacion(d: DatosReporte) -> dict:
    campos = [_campo("Resultado de la consulta", ESTADOS.get(d.clinico["estado"], d.clinico["estado"]))]
    if d.clinico["texto_filtrado"]:
        campos.append(_campo("Pregunta realizada", d.clinico["texto_filtrado"]))
    reco = d.generacion["recomendacion"]
    if reco is None:
        return _bloque("RECOMENDACION", campos=campos,
                       parrafos=[d.clinico["mensaje"] or "La consulta no tiene una recomendación verificada."])
    items = [{"texto": f"{i}. {TIPOS_PASO.get(p['tipo'], p['tipo'])}: {p['texto']}"
                       + (f" [{', '.join(p['citas'])}]" if p.get("citas") else ""), "detalle": []}
             for i, p in enumerate(reco.get("recomendacion") or [], start=1)]
    return _bloque("RECOMENDACION", campos=campos, parrafos=[reco["resumen"]] if reco.get("resumen") else [], items=items)


def _evidencias(d: DatosReporte) -> dict:
    citas = d.generacion["citas"]
    if not citas:
        return _bloque("EVIDENCIAS", parrafos=["La consulta no tiene evidencias citadas."])
    items = []
    for c in citas:
        detalle = [c["documento"]]
        if c.get("seccion"):
            detalle.append(f"Sección: {c['seccion']}")
        paginas = _paginas(c.get("pagina_inicio"), c.get("pagina_fin"))
        if paginas:
            detalle.append(paginas)
        if c.get("agregado_por_referencia_de"):
            detalle.append(f"Agregado por referencia de {c['agregado_por_referencia_de']}")
        detalle.append(f"Extracto: «{c['extracto']}»")
        if c.get("extracto_traducido"):
            detalle.append(f"{c.get('etiqueta_traduccion') or 'Traducción de apoyo'}: «{c['extracto_traducido']}»")
        items.append({"texto": f"{c['etiqueta']} · {c.get('fuente') or c['documento']}", "detalle": detalle})
    return _bloque("EVIDENCIAS", items=items)


def _advertencias(d: DatosReporte) -> dict:
    lista = (d.generacion["recomendacion"] or {}).get("advertencias") or []
    if not lista:
        return _bloque("ADVERTENCIAS", parrafos=["Sin advertencias."])
    return _bloque("ADVERTENCIAS", items=[{"texto": a, "detalle": []} for a in lista])


def _verificacion(d: DatosReporte) -> dict:
    v = d.generacion["verificacion"]
    if v is None:
        return _bloque("VERIFICACION", parrafos=["La respuesta no llegó a verificarse."])
    detalle = None
    if v.get("relevancia_maxima") is not None:
        detalle = f"Relevancia máxima {v['relevancia_maxima']:.3f} frente al umbral {v['umbral_relevancia']:.3f}"
    return _bloque("VERIFICACION", campos=[
        _campo("6.1 Citas textuales", _control(v["valida_citas"])),
        _campo("6.2 Consistencia y dosis", _control(v["valida_consistencia"])),
        _campo("6.3 Suficiencia de la evidencia", _control(v["valida_evidencia"]) + (f" ({detalle})" if detalle else "")),
        _campo("Intento evaluado", str(v["numero_intento"])),
    ])


def _decision(d: DatosReporte) -> dict:
    dec = d.clinico["decision"]
    if dec is None:
        return _bloque("DECISION", parrafos=["Sin decisión registrada."])
    return _bloque("DECISION", campos=[
        _campo("Tipo de decisión", TIPOS_DECISION.get(dec["tipo_decision"], dec["tipo_decision"])),
        _campo("Nota", dec["nota"] or "Sin nota"),
        _campo("Registrada por", dec.get("registrada_por") or "Sin dato"),
        _campo("Fecha y hora", fecha_hora(dec["fecha_registro"])),
    ])


_EXPEDIENTE = {"PACIENTE": _paciente, "CLASIFICACION": _clasificacion, "RECOMENDACION": _recomendacion,
               "EVIDENCIAS": _evidencias, "ADVERTENCIAS": _advertencias, "VERIFICACION": _verificacion,
               "DECISION": _decision}


# ---------------------------------------------------------------------------
# Bloques del cuidador (solo frases fijas)
# ---------------------------------------------------------------------------
def _cuidador_paciente(d: DatosReporte) -> dict:
    return _bloque("PACIENTE", "Datos de su niña o niño", campos=[
        _campo("Nombre", d.nombres_apellidos), _campo("Historia clínica", d.numero_hc),
        _campo("Edad", _edad(d.edad_meses)), _campo("Fecha de la evaluación", fecha_hora(d.clinico["fecha_hora_inicio"]))])


def _cuidador_clasificacion(d: DatosReporte, fr: dict) -> dict:
    c = d.clinico["clasificacion"]
    clave = c["categoria"] if c and c["categoria"] in fr["clasificacion"] else "SIN_CLASIFICACION"
    parrafos = [fr["clasificacion"][clave]]
    if clave.startswith("ANEMIA_"):
        parrafos.append(fr["que_es_anemia"])
    if c and c["requiere_derivacion"]:
        parrafos.append(fr["derivacion"])
    return _bloque("CLASIFICACION", fr["titulos"]["resultado"], parrafos=parrafos)


def tipos_de_paso_aceptados(d: DatosReporte) -> list[str]:
    """Tipos de paso, sin repetir y en orden, solo si el profesional aceptó la recomendación."""
    dec = d.clinico["decision"]
    reco = d.generacion["recomendacion"]
    if reco is None or dec is None or dec["tipo_decision"] != "ACEPTA_RECOMENDACION":
        return []
    tipos: list[str] = []
    for p in reco.get("recomendacion") or []:
        t = p["tipo"] if p["tipo"] in TIPOS_PASO else "OTRO"
        if t not in tipos:
            tipos.append(t)
    return tipos


def _cuidador_indicaciones(d: DatosReporte, fr: dict) -> dict:
    tipos = tipos_de_paso_aceptados(d)
    textos = [fr["pasos"][t] for t in tipos] or [fr["pasos_no_disponibles"]]
    return _bloque("RECOMENDACION", fr["titulos"]["indicaciones"], items=[{"texto": t, "detalle": []} for t in textos])


def _cuidador_recuerde(fr: dict) -> dict:
    return _bloque("RECUERDE", fr["titulos"]["recuerde"], items=[{"texto": t, "detalle": []} for t in fr["indicaciones_generales"]])


# ---------------------------------------------------------------------------
# Contenido completo
# ---------------------------------------------------------------------------
def armar(d: DatosReporte, destino: str, secciones: list[str], generado_por: str, establecimiento: str,
          id_consulta: str) -> dict:
    """Contenido del reporte, sin número ni fecha de emisión (los agrega el PDF)."""
    fr = frases()
    revision_pendiente = destino == CUIDADOR and not fr.get("revisado", False)
    avisos = ([AVISO_PRUEBA] if d.modo_prueba else []) + ([AVISO_REVISION] if revision_pendiente else [])
    if destino == EXPEDIENTE:
        bloques = [_EXPEDIENTE[s](d) for s in secciones if s in _EXPEDIENTE]
        titulo, introduccion = TITULO_EXPEDIENTE, None
    else:
        constructores = {"PACIENTE": lambda: _cuidador_paciente(d), "CLASIFICACION": lambda: _cuidador_clasificacion(d, fr),
                         "RECOMENDACION": lambda: _cuidador_indicaciones(d, fr)}
        bloques = [constructores[s]() for s in secciones if s in constructores] + [_cuidador_recuerde(fr)]
        titulo, introduccion = fr["titulo"], fr["introduccion"]
    return {
        "id_consulta": id_consulta, "destino": destino, "secciones": secciones, "modo_prueba": d.modo_prueba,
        "revision_pendiente": revision_pendiente, "titulo": titulo, "introduccion": introduccion,
        "establecimiento": establecimiento, "fecha_consulta": d.clinico["fecha_hora_inicio"], "avisos": avisos,
        "bloques": bloques, "frase_final": FRASE_FINAL, "firma": "FIRMA" in secciones, "generado_por": generado_por,
    }
