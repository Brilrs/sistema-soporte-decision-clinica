"""Parámetros clínicos y del sistema (M12, HU14; Sprint 3, parte E1a): lectura, historial y huella.

Con la sesión de cdss_clinica (solo lectura sobre configuracion y conocimiento). Grupos:
- editables desde M12 por el Coordinador CRED (parte E1b): puntos de corte (tramos fijos de 6 a 23 y
  de 24 a 59 meses), ajuste por altitud y vigencia del tamizaje (DIAS_VIGENCIA_TAMIZAJE);
- de solo lectura (decisión 4): riesgo por clasificación (categoria_anemia, sin versionar) y los
  parámetros de recuperación, del modelo y de la indexación, que se cambian solo por migración.
Los parámetros sin uso en el código (EDAD_MIN_CLASIFICACION, EDAD_MAX_CLASIFICACION,
REINTENTOS_MAXIMOS y MODELO_RESPALDO) no se muestran.

La versión de cada grupo editable es el SHA-256 de los ids vigentes del grupo: si otro cambio cerró o
creó una fila, la versión cambia (control optimista de E1b). Todos los órdenes son explícitos sobre
enteros o fechas, o se hacen en Python: nada depende de la colación de la base."""
import hashlib
import json
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

GRUPOS_EDITABLES = ("puntos_corte", "ajuste_altitud", "vigencia_tamizaje")
CLAVE_VIGENCIA = "DIAS_VIGENCIA_TAMIZAJE"
CLAVES_SOLO_LECTURA: dict[str, list[str]] = {
    "recuperacion": ["CANDIDATOS_BUSQUEDA", "CANDIDATOS_BUSQUEDA_AMPLIADA", "RRF_K", "CANDIDATOS_RERANKER",
                     "MAX_LONGITUD_RERANKER", "FRAGMENTOS_ENVIADOS", "UMBRAL_RELEVANCIA", "UMBRAL_DOMINIO",
                     "BONIFICACION_EDAD"],
    "modelo": ["MODELO_LLM", "VERSION_PROMPT", "MAX_TOKENS_SALIDA", "TIMEOUT_LLM_S", "RAZONAMIENTO_LLM", "ESFUERZO_LLM",
               "IDIOMA_RESPUESTA_DEFECTO", "PRECIO_ENTRADA_USD_MTOK", "PRECIO_SALIDA_USD_MTOK"],
    "indexacion": ["TAMANO_FRAGMENTO_TOKENS", "TAMANO_MAX_FRAGMENTO_TOKENS", "SOLAPAMIENTO_TOKENS"],
}
# No se usan en el código (diagnóstico de la fase 0): no se muestran en M12.
CLAVES_SIN_USO = frozenset({"EDAD_MIN_CLASIFICACION", "EDAD_MAX_CLASIFICACION", "REINTENTOS_MAXIMOS", "MODELO_RESPALDO"})
GRUPOS_HISTORIAL = (*GRUPOS_EDITABLES, *CLAVES_SOLO_LECTURA)

Lectura = Session | Connection


def _decimal(v) -> float | None:
    return None if v is None else float(v)


def _documento(f) -> dict | None:
    if f["id_documento"] is None:
        return None
    return {"id_documento": f["id_documento"], "codigo": f["codigo_documento"], "titulo": f["titulo_documento"]}


def _comunes(f) -> dict:
    return {"documento": _documento(f), "referencia": f["referencia"], "motivo_cambio": f["motivo_cambio"],
            "verificado": f["verificado"], "vigente_desde": f["vigente_desde"], "modificado_por": f["modificado_por"]}


def version_de(grupo: str, ids: list[int]) -> str:
    """SHA-256 de los ids vigentes del grupo, ordenados como enteros."""
    return hashlib.sha256(f"{grupo}:{','.join(str(i) for i in sorted(ids))}".encode()).hexdigest()


_JOIN_COMUNES = """
      LEFT JOIN conocimiento.documento_fuente d ON d.id_documento = x.id_documento
      JOIN seguridad.usuario us ON us.id_usuario = x.modificado_por
"""
_CAMPOS_COMUNES = """x.id_documento::text, d.codigo_documento, d.titulo AS titulo_documento, x.referencia,
           x.motivo_cambio, x.verificado, x.vigente_desde, x.vigente_hasta, us.nombre_completo AS modificado_por"""


def _umbrales(sesion: Lectura, solo_vigentes: bool = True) -> list:
    return sesion.execute(text(f"""
    SELECT x.id_umbral, x.edad_min_meses, x.edad_max_meses, c.nombre AS categoria, c.nivel_riesgo, c.orden,
           x.hb_min_g_dl, x.hb_max_g_dl, {_CAMPOS_COMUNES}
      FROM configuracion.umbral_hemoglobina x
      JOIN configuracion.categoria_anemia c ON c.id_categoria = x.id_categoria {_JOIN_COMUNES}
     WHERE {"x.vigente_hasta IS NULL" if solo_vigentes else "true"}""")).mappings().all()


def _ajustes(sesion: Lectura, solo_vigentes: bool = True) -> list:
    return sesion.execute(text(f"""
    SELECT x.id_ajuste, x.altitud_min_msnm, x.altitud_max_msnm, x.ajuste_g_dl, {_CAMPOS_COMUNES}
      FROM configuracion.ajuste_altitud x {_JOIN_COMUNES}
     WHERE {"x.vigente_hasta IS NULL" if solo_vigentes else "true"}""")).mappings().all()


def _parametros(sesion: Lectura, claves: list[str] | None, solo_vigentes: bool = True) -> list:
    condiciones = ["x.vigente_hasta IS NULL" if solo_vigentes else "true"]
    valores: dict = {}
    if claves is not None:
        condiciones.append("x.clave = ANY(:claves)")
        valores["claves"] = claves
    return sesion.execute(text(f"""
    SELECT x.id_parametro, x.clave, x.valor, x.tipo_dato, x.valor_minimo, x.valor_maximo, x.descripcion,
           {_CAMPOS_COMUNES}
      FROM configuracion.parametro_sistema x {_JOIN_COMUNES}
     WHERE {" AND ".join(condiciones)}"""), valores).mappings().all()


def _categorias(sesion: Lectura) -> list:
    return sesion.execute(text("""SELECT nombre, nivel_riesgo, requiere_derivacion, orden
                                    FROM configuracion.categoria_anemia""")).mappings().all()


# ---------------------------------------------------------------------------
# GET /api/parametros
# ---------------------------------------------------------------------------
def puntos_corte(sesion: Lectura) -> dict:
    filas = sorted(_umbrales(sesion), key=lambda f: (f["edad_min_meses"], f["edad_max_meses"], f["orden"]))
    tramos: dict[tuple[int, int], list] = {}
    for f in filas:
        tramos.setdefault((f["edad_min_meses"], f["edad_max_meses"]), []).append({
            "id_umbral": f["id_umbral"], "categoria": f["categoria"], "nivel_riesgo": f["nivel_riesgo"],
            "hb_min_g_dl": _decimal(f["hb_min_g_dl"]), "hb_max_g_dl": _decimal(f["hb_max_g_dl"]), **_comunes(f)})
    return {"version": version_de("puntos_corte", [f["id_umbral"] for f in filas]),
            "tramos": [{"edad_min_meses": a, "edad_max_meses": b, "categorias": cats} for (a, b), cats in tramos.items()]}


def ajuste_altitud(sesion: Lectura) -> dict:
    filas = sorted(_ajustes(sesion), key=lambda f: (f["altitud_min_msnm"], f["altitud_max_msnm"]))
    return {"version": version_de("ajuste_altitud", [f["id_ajuste"] for f in filas]),
            "rangos": [{"id_ajuste": f["id_ajuste"], "altitud_min_msnm": f["altitud_min_msnm"],
                        "altitud_max_msnm": f["altitud_max_msnm"], "ajuste_g_dl": _decimal(f["ajuste_g_dl"]),
                        **_comunes(f)} for f in filas]}


def _parametro(f) -> dict:
    return {"id_parametro": f["id_parametro"], "clave": f["clave"], "valor": f["valor"], "tipo_dato": f["tipo_dato"],
            "valor_minimo": _decimal(f["valor_minimo"]), "valor_maximo": _decimal(f["valor_maximo"]),
            "descripcion": f["descripcion"], **_comunes(f)}


def vigencia_tamizaje(sesion: Lectura) -> dict:
    filas = _parametros(sesion, [CLAVE_VIGENCIA])
    if not filas:
        raise LookupError(f"No hay valor vigente para {CLAVE_VIGENCIA}")
    f = filas[0]
    return {"version": version_de("vigencia_tamizaje", [f["id_parametro"]]), **_parametro(f)}


def solo_lectura(sesion: Lectura, grupo: str) -> list[dict]:
    claves = CLAVES_SOLO_LECTURA[grupo]
    por_clave = {f["clave"]: f for f in _parametros(sesion, claves)}
    return [_parametro(por_clave[c]) for c in claves if c in por_clave]


def riesgo(sesion: Lectura) -> list[dict]:
    return [dict(f) for f in sorted(_categorias(sesion), key=lambda f: f["orden"])]


def parametros(sesion: Lectura, puede_editar: bool, modo_evaluacion: bool) -> dict:
    return {
        "puede_editar": puede_editar, "modo_evaluacion": modo_evaluacion,
        "puntos_corte": puntos_corte(sesion), "ajuste_altitud": ajuste_altitud(sesion),
        "vigencia_tamizaje": vigencia_tamizaje(sesion), "riesgo": riesgo(sesion),
        **{g: solo_lectura(sesion, g) for g in CLAVES_SOLO_LECTURA},
    }


# ---------------------------------------------------------------------------
# GET /api/parametros/historial
# ---------------------------------------------------------------------------
def _version_historial(grupo: str, tabla: str, ident: int, elemento: str, valores: dict, f) -> dict:
    return {"grupo": grupo, "tabla": tabla, "id": ident, "elemento": elemento, "valores": valores,
            "vigente_hasta": f["vigente_hasta"], "vigente": f["vigente_hasta"] is None, **_comunes(f)}


def _historial_de(sesion: Lectura, grupo: str) -> list[dict]:
    if grupo == "puntos_corte":
        return [_version_historial(grupo, "umbral_hemoglobina", f["id_umbral"],
                                   f"{f['edad_min_meses']} a {f['edad_max_meses']} meses · {f['categoria']}",
                                   {"hb_min_g_dl": _decimal(f["hb_min_g_dl"]), "hb_max_g_dl": _decimal(f["hb_max_g_dl"])}, f)
                for f in _umbrales(sesion, solo_vigentes=False)]
    if grupo == "ajuste_altitud":
        return [_version_historial(grupo, "ajuste_altitud", f["id_ajuste"],
                                   f"{f['altitud_min_msnm']} a {f['altitud_max_msnm']} m.s.n.m.",
                                   {"ajuste_g_dl": _decimal(f["ajuste_g_dl"])}, f)
                for f in _ajustes(sesion, solo_vigentes=False)]
    claves = [CLAVE_VIGENCIA] if grupo == "vigencia_tamizaje" else CLAVES_SOLO_LECTURA[grupo]
    return [_version_historial(grupo, "parametro_sistema", f["id_parametro"], f["clave"], {"valor": f["valor"]}, f)
            for f in _parametros(sesion, claves, solo_vigentes=False)]


def historial(sesion: Lectura, grupo: str | None, limite: int, desplazamiento: int) -> tuple[list[dict], int]:
    """Versiones (vigentes y cerradas) de uno o de todos los grupos, de la más reciente a la más
    antigua: inicio de vigencia descendente, luego el grupo (en el orden de GRUPOS_HISTORIAL) y el id
    descendente. Se ordena en Python con esa clave explícita."""
    grupos = [grupo] if grupo else list(GRUPOS_HISTORIAL)
    versiones = [v for g in grupos for v in _historial_de(sesion, g)]
    versiones.sort(key=lambda v: (-v["vigente_desde"].timestamp(), GRUPOS_HISTORIAL.index(v["grupo"]), -v["id"]))
    return versiones[desplazamiento:desplazamiento + limite], len(versiones)


# ---------------------------------------------------------------------------
# GET /api/parametros/huella
# ---------------------------------------------------------------------------
def _texto(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    return str(v)


def _sha(datos) -> str:
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def componentes_huella(sesion: Lectura) -> dict[str, list]:
    """Valores vigentes que determinan lo que el sistema responde, en listas ordenadas en Python."""
    umbrales = sorted(([f["edad_min_meses"], f["edad_max_meses"], f["orden"], f["categoria"], _texto(f["hb_min_g_dl"]),
                        _texto(f["hb_max_g_dl"]), f["id_documento"]] for f in _umbrales(sesion)), key=lambda x: x[:3])
    ajustes = sorted(([f["altitud_min_msnm"], f["altitud_max_msnm"], _texto(f["ajuste_g_dl"]), f["id_documento"]]
                      for f in _ajustes(sesion)), key=lambda x: x[:2])
    categorias = sorted(([f["orden"], f["nombre"], f["nivel_riesgo"], f["requiere_derivacion"]]
                         for f in _categorias(sesion)), key=lambda x: x[0])
    params = sorted(([f["clave"], f["valor"], f["tipo_dato"]] for f in _parametros(sesion, None)), key=lambda x: x[0])
    indexacion = sorted(([str(f.id_documento), f.codigo_documento, f.version] for f in sesion.execute(text(
        """SELECT d.id_documento, d.codigo_documento, max(f.version_indexacion) AS version
             FROM conocimiento.documento_fuente d
             JOIN conocimiento.fragmento f ON f.id_documento = d.id_documento
            WHERE d.estado = 'VIGENTE' AND d.estado_indexacion = 'COMPLETADA'
            GROUP BY d.id_documento, d.codigo_documento"""))), key=lambda x: x[0])
    version_prompt = next((p[1] for p in params if p[0] == "VERSION_PROMPT"), None)
    return {"puntos_corte": umbrales, "ajuste_altitud": ajustes, "categorias": categorias,
            "parametros_sistema": params, "indexacion": indexacion, "version_prompt": [version_prompt]}


def huella(sesion: Lectura) -> dict:
    componentes = componentes_huella(sesion)
    por_componente = {nombre: _sha(valores) for nombre, valores in componentes.items()}
    calculada = sesion.execute(text("SELECT now()")).scalar_one()
    return {
        "huella": _sha(por_componente), "algoritmo": "SHA-256", "calculada_en": calculada,
        "version_prompt": componentes["version_prompt"][0],
        "componentes": [{"nombre": n, "huella": por_componente[n], "elementos": len(componentes[n])} for n in componentes],
        "indexacion": [{"id_documento": d, "codigo": c, "version_indexacion": v} for d, c, v in componentes["indexacion"]],
    }
