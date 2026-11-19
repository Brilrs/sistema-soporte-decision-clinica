"""Edición de los parámetros de M12 (HU14; Sprint 3, parte E1b), con la sesión de cdss_admin.

Un PUT por grupo (puntos de corte, ajuste por altitud y vigencia del tamizaje) con la tabla completa.
En una sola transacción:
1. bloqueo del grupo (pg_advisory_xact_lock) y control optimista: la versión enviada debe ser la del
   grupo vigente (SHA-256 de sus ids); si no, 409;
2. validación: errores duros (422), advertencias que exigen confirmacion_escrita = «CONFIRMO» (422
   REQUIERE_CONFIRMACION) y, si nada cambia, 422 SIN_CAMBIOS. Las reglas están en parametros_reglas;
3. primero se CIERRAN las versiones que cambian (vigente_hasta = now()) y DESPUÉS se insertan las
   nuevas (vigente_desde = now(), la misma marca): las restricciones EXCLUDE y el índice único de los
   parámetros vigentes no son diferibles. Las filas sin cambio conservan su id;
4. evento PARAMETRO_CAMBIADO con ids, valores antes y después, motivo, referencia y advertencias.
Confirmar contra la norma es un cambio sin cambio de valor: verificado de falso a verdadero, con
referencia. Quitar la verificación sin cambiar el valor no se admite."""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auditoria import registrar_evento
from app.services import parametros as lectura
from app.services import parametros_reglas as R

EVENTO = "PARAMETRO_CAMBIADO"
MENSAJE_VERSION = "Los parámetros cambiaron desde que los abrió: recargue la página para ver los valores vigentes"
MENSAJE_SIN_CAMBIOS = "No hay cambios: los valores y su estado de verificación son los vigentes"
MENSAJE_CONFIRMACION = f"El cambio tiene advertencias: revíselas y escriba {R.CONFIRMACION} para guardarlo"
TABLAS = {"puntos_corte": "configuracion.umbral_hemoglobina", "ajuste_altitud": "configuracion.ajuste_altitud",
          "vigencia_tamizaje": "configuracion.parametro_sistema"}


class ErrorEdicion(Exception):
    """Respuesta de error con el formato del proyecto (detail y, si corresponde, errores o advertencias)."""

    def __init__(self, estado: int, detail: str, codigo: str, errores: list[dict] | None = None,
                 advertencias: list[dict] | None = None, version_actual: str | None = None):
        super().__init__(detail)
        self.estado, self.detail, self.codigo = estado, detail, codigo
        self.errores, self.advertencias, self.version_actual = errores, advertencias, version_actual

    def cuerpo(self) -> dict:
        cuerpo: dict = {"detail": self.detail, "codigo": self.codigo}
        if self.errores is not None:
            cuerpo["errores"] = self.errores
        if self.advertencias is not None:
            cuerpo["advertencias"] = self.advertencias
        if self.version_actual is not None:
            cuerpo["version_actual"] = self.version_actual
        return cuerpo


@dataclass
class Edicion:
    """Lo común a los tres PUT (ya validado por el modelo de la ruta)."""
    version: str
    motivo_cambio: str
    referencia: str | None
    id_documento: str | None
    confirmacion_escrita: str | None
    id_usuario: str


@dataclass
class Revision:
    errores: list[dict] = field(default_factory=list)
    advertencias: list[dict] = field(default_factory=list)

    def error(self, campo: str, mensaje: str) -> None:
        self.errores.append({"campo": campo, "mensaje": mensaje})

    def advertencia(self, campo: str, mensaje: str) -> None:
        self.advertencias.append({"campo": campo, "mensaje": mensaje})


def _texto(v: Decimal | None) -> str:
    return "sin límite" if v is None else f"{v:.1f}"


def _un_decimal(v: Decimal, paso: Decimal) -> bool:
    return v == v.quantize(paso)


def _errores_422(rev: Revision) -> ErrorEdicion:
    resumen = "; ".join(f"{e['campo']}: {e['mensaje']}" for e in rev.errores)
    return ErrorEdicion(422, f"Revise los datos ingresados. {resumen}", "VALIDACION", errores=rev.errores)


def _bloquear(sesion: Session, grupo: str) -> None:
    sesion.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"cdss.parametros.{grupo}"})


def _comprobar_version(enviada: str, actual: str) -> None:
    if enviada != actual:
        raise ErrorEdicion(409, MENSAJE_VERSION, "VERSION_DESACTUALIZADA", version_actual=actual)


def _comprobar_documento(sesion: Session, e: Edicion, rev: Revision) -> None:
    if e.id_documento is None:
        return
    existe = sesion.execute(text("SELECT 1 FROM conocimiento.documento_fuente WHERE id_documento = CAST(:d AS uuid)"),
                            {"d": e.id_documento}).first()
    if existe is None:
        rev.error("id_documento", "no corresponde a ninguna norma registrada")


def _verificacion(rev: Revision, campo: str, antes: bool, despues: bool, valores_iguales: bool, e: Edicion) -> bool:
    """¿La fila cambia? Con valores iguales, solo si se confirma contra la norma (falso a verdadero).
    Quitar la verificación sin cambiar el valor es un error."""
    if despues and not e.referencia:
        rev.error("referencia", "es obligatoria cuando un valor queda verificado contra la norma")
    if valores_iguales:
        if antes and not despues:
            rev.error(f"{campo}.verificado", "no se puede quitar la verificación sin cambiar el valor")
            return False
        return despues and not antes
    return True


def _confirmar(rev: Revision, e: Edicion) -> None:
    if rev.errores:
        raise _errores_422(rev)
    if rev.advertencias and (e.confirmacion_escrita or "").strip() != R.CONFIRMACION:
        raise ErrorEdicion(422, MENSAJE_CONFIRMACION, "REQUIERE_CONFIRMACION", advertencias=rev.advertencias)


def _cerrar(sesion: Session, grupo: str, ids: list[int]) -> list[int]:
    columna = {"puntos_corte": "id_umbral", "ajuste_altitud": "id_ajuste", "vigencia_tamizaje": "id_parametro"}[grupo]
    if not ids:
        return []
    cerrados = sesion.execute(text(f"""UPDATE {TABLAS[grupo]} SET vigente_hasta = now()
                                         WHERE {columna} = ANY(:ids) AND vigente_hasta IS NULL
                                     RETURNING {columna}"""), {"ids": ids}).scalars().all()
    return sorted(cerrados)


def _evento(sesion: Session, grupo: str, e: Edicion, cerrados: list[int], creados: list[int], cambios: list[dict],
            advertencias: list[dict]) -> dict:
    resumen = {"grupo": grupo, "cerrados": cerrados, "creados": creados, "cambios": cambios,
               "advertencias_confirmadas": [a["mensaje"] for a in advertencias]}
    registrar_evento(sesion, EVENTO, e.id_usuario, TABLAS[grupo], None, {
        **resumen, "motivo_cambio": e.motivo_cambio, "referencia": e.referencia, "id_documento": e.id_documento})
    return resumen


# ---------------------------------------------------------------------------
# Puntos de corte
# ---------------------------------------------------------------------------
def editar_puntos_corte(sesion: Session, e: Edicion, tramos: list[dict]) -> dict:
    """tramos: [{edad_min_meses, edad_max_meses, categorias: [{categoria, hb_min_g_dl, hb_max_g_dl, verificado}]}]."""
    grupo = "puntos_corte"
    _bloquear(sesion, grupo)
    vigentes = lectura._umbrales(sesion)
    _comprobar_version(e.version, lectura.version_de(grupo, [f["id_umbral"] for f in vigentes]))
    rev = Revision()
    _comprobar_documento(sesion, e, rev)
    por_clave = {(f["edad_min_meses"], f["edad_max_meses"], f["categoria"]): f for f in vigentes}
    orden = {f["categoria"]: f["orden"] for f in vigentes}
    tramos_vigentes = sorted({(f["edad_min_meses"], f["edad_max_meses"]) for f in vigentes})
    categorias_vigentes = sorted(orden, key=lambda c: orden[c])

    # Estructura: los tramos y las categorías son los vigentes, sin repetir.
    enviados = [(t["edad_min_meses"], t["edad_max_meses"]) for t in tramos]
    if sorted(enviados) != tramos_vigentes:
        rev.error("tramos", "los tramos de edad son fijos: "
                  + ", ".join(f"{a} a {b} meses" for a, b in tramos_vigentes))
    for i, t in enumerate(tramos):
        nombres = [c["categoria"] for c in t["categorias"]]
        if sorted(nombres, key=lambda c: orden.get(c, 99)) != categorias_vigentes:
            rev.error(f"tramos.{i}.categorias", "deben ser una vez cada una: " + ", ".join(categorias_vigentes))
    if rev.errores:
        raise _errores_422(rev)

    cambios, nuevas, cerrar = [], [], []
    for i, t in enumerate(tramos):
        cats = sorted(enumerate(t["categorias"]), key=lambda x: -orden[x[1]["categoria"]])  # de la más severa a sin anemia
        anterior = None
        for posicion, (j, c) in enumerate(cats):
            campo = f"tramos.{i}.categorias.{j}"
            hb_min, hb_max = c["hb_min_g_dl"], c["hb_max_g_dl"]
            mas_severa, sin_anemia = posicion == 0, posicion == len(cats) - 1
            if mas_severa and hb_min is not None:
                rev.error(f"{campo}.hb_min_g_dl", "la categoría más severa no tiene límite inferior")
            if sin_anemia and hb_max is not None:
                rev.error(f"{campo}.hb_max_g_dl", "la categoría sin anemia no tiene límite superior")
            if not mas_severa and hb_min is None:
                rev.error(f"{campo}.hb_min_g_dl", "es obligatorio")
            if not sin_anemia and hb_max is None:
                rev.error(f"{campo}.hb_max_g_dl", "es obligatorio")
            for nombre, v in (("hb_min_g_dl", hb_min), ("hb_max_g_dl", hb_max)):
                if v is None:
                    continue
                if not _un_decimal(v, R.PASO_HB):
                    rev.error(f"{campo}.{nombre}", "admite un solo decimal")
                if not R.HB_MIN_PLAUSIBLE <= v <= R.HB_MAX_PLAUSIBLE:
                    rev.error(f"{campo}.{nombre}", f"debe estar entre {R.HB_MIN_PLAUSIBLE} y {R.HB_MAX_PLAUSIBLE} g/dL")
            if hb_min is not None and hb_max is not None and hb_min > hb_max:
                rev.error(f"{campo}.hb_min_g_dl", "no puede ser mayor que hb_max_g_dl")
            # Contigüidad: el mínimo de esta categoría es el máximo de la más severa anterior más 0.1.
            if anterior is not None and anterior["hb_max_g_dl"] is not None and hb_min is not None:
                esperado = anterior["hb_max_g_dl"] + R.PASO_HB
                if hb_min != esperado:
                    rev.error(f"{campo}.hb_min_g_dl", f"debe ser {esperado:.1f}: los límites de Hb de categorías "
                              "vecinas deben ser contiguos, sin huecos ni traslapes")
            anterior = c

            previo = por_clave.get((t["edad_min_meses"], t["edad_max_meses"], c["categoria"]))
            if previo is None:
                continue
            for nombre, v in (("hb_min_g_dl", hb_min), ("hb_max_g_dl", hb_max)):
                if v is not None and previo[nombre] is not None and abs(v - previo[nombre]) > R.CAMBIO_HB_ADVERTENCIA:
                    rev.advertencia(f"{campo}.{nombre}", f"{t['edad_min_meses']} a {t['edad_max_meses']} meses, "
                                    f"{c['categoria']}: el límite pasa de {_texto(previo[nombre])} a {_texto(v)} g/dL "
                                    f"(más de {R.CAMBIO_HB_ADVERTENCIA} g/dL)")
            if (sin_anemia and hb_min is not None and hb_min != previo["hb_min_g_dl"]
                    and not R.SIN_ANEMIA_MIN_ADVERTENCIA <= hb_min <= R.SIN_ANEMIA_MAX_ADVERTENCIA):
                rev.advertencia(f"{campo}.hb_min_g_dl", f"{t['edad_min_meses']} a {t['edad_max_meses']} meses: el punto de "
                                f"corte de sin anemia ({_texto(hb_min)} g/dL) está fuera de {R.SIN_ANEMIA_MIN_ADVERTENCIA} "
                                f"a {R.SIN_ANEMIA_MAX_ADVERTENCIA} g/dL")
            iguales = previo["hb_min_g_dl"] == hb_min and previo["hb_max_g_dl"] == hb_max
            if _verificacion(rev, campo, previo["verificado"], bool(c.get("verificado")), iguales, e):
                cerrar.append(previo["id_umbral"])
                nuevas.append((previo, c))
                cambios.append({"elemento": f"{t['edad_min_meses']} a {t['edad_max_meses']} meses · {c['categoria']}",
                                "antes": {"hb_min_g_dl": _num(previo["hb_min_g_dl"]), "hb_max_g_dl": _num(previo["hb_max_g_dl"]),
                                          "verificado": previo["verificado"]},
                                "despues": {"hb_min_g_dl": _num(hb_min), "hb_max_g_dl": _num(hb_max),
                                            "verificado": bool(c.get("verificado"))}})
    _confirmar(rev, e)
    if not cambios:
        raise ErrorEdicion(422, MENSAJE_SIN_CAMBIOS, "SIN_CAMBIOS")

    ids_categoria = dict(sesion.execute(text("SELECT nombre, id_categoria FROM configuracion.categoria_anemia")).all())
    cerrados = _cerrar(sesion, grupo, cerrar)
    creados = [insertar_umbral(sesion, e, previo, c, ids_categoria[c["categoria"]]) for previo, c in nuevas]
    resumen = _evento(sesion, grupo, e, cerrados, sorted(creados), cambios, rev.advertencias)
    return {"grupo": lectura.puntos_corte(sesion), "resumen": resumen}


def insertar_umbral(sesion: Session, e: Edicion, previo, c: dict, id_categoria: int) -> int:
    return sesion.execute(text(
        """INSERT INTO configuracion.umbral_hemoglobina
             (id_documento, id_categoria, edad_min_meses, edad_max_meses, hb_min_g_dl, hb_max_g_dl, vigente_desde,
              modificado_por, motivo_cambio, referencia, verificado)
           VALUES (CAST(:doc AS uuid), :cat, :emin, :emax, :hmin, :hmax, now(), CAST(:u AS uuid), :motivo, :ref, :ver)
           RETURNING id_umbral"""),
        {"doc": e.id_documento or previo["id_documento"], "cat": id_categoria, "emin": previo["edad_min_meses"],
         "emax": previo["edad_max_meses"], "hmin": c["hb_min_g_dl"], "hmax": c["hb_max_g_dl"], "u": e.id_usuario,
         "motivo": e.motivo_cambio, "ref": e.referencia, "ver": bool(c.get("verificado"))}).scalar_one()


def _num(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


# ---------------------------------------------------------------------------
# Ajuste por altitud
# ---------------------------------------------------------------------------
def editar_ajuste_altitud(sesion: Session, e: Edicion, rangos: list[dict]) -> dict:
    """rangos: [{altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, verificado}], de menor a mayor altitud."""
    grupo = "ajuste_altitud"
    _bloquear(sesion, grupo)
    vigentes = sorted(lectura._ajustes(sesion), key=lambda f: f["altitud_min_msnm"])
    _comprobar_version(e.version, lectura.version_de(grupo, [f["id_ajuste"] for f in vigentes]))
    rev = Revision()
    _comprobar_documento(sesion, e, rev)
    if not rangos:
        rev.error("rangos", "debe haber al menos un rango")
        raise _errores_422(rev)

    anterior = None
    for i, r in enumerate(rangos):
        campo = f"rangos.{i}"
        amin, amax, ajuste = r["altitud_min_msnm"], r["altitud_max_msnm"], r["ajuste_g_dl"]
        if i == 0 and amin != 0:
            rev.error(f"{campo}.altitud_min_msnm", "el primer rango empieza en 0 m.s.n.m.")
        if anterior is not None and amin != anterior["altitud_max_msnm"] + 1:
            rev.error(f"{campo}.altitud_min_msnm", f"debe ser {anterior['altitud_max_msnm'] + 1}: los rangos de altitud "
                      "deben ser contiguos, sin huecos ni traslapes")
        if amin > amax:
            rev.error(f"{campo}.altitud_max_msnm", "no puede ser menor que altitud_min_msnm")
        if not _un_decimal(ajuste, R.PASO_AJUSTE):
            rev.error(f"{campo}.ajuste_g_dl", "admite un solo decimal")
        if not R.AJUSTE_MIN <= ajuste <= R.AJUSTE_MAX:
            rev.error(f"{campo}.ajuste_g_dl", f"debe estar entre {R.AJUSTE_MIN} y {R.AJUSTE_MAX} g/dL")
        if anterior is not None and ajuste < anterior["ajuste_g_dl"]:
            rev.error(f"{campo}.ajuste_g_dl", "no puede ser menor que el del rango anterior: el ajuste no decrece con la altitud")
        anterior = r
    if rangos[-1]["altitud_max_msnm"] < R.COBERTURA_MINIMA_ALTITUD:
        rev.error(f"rangos.{len(rangos) - 1}.altitud_max_msnm",
                  f"los rangos deben cubrir al menos hasta {R.COBERTURA_MINIMA_ALTITUD} m.s.n.m.")
    if rev.errores:
        raise _errores_422(rev)

    por_rango = {(f["altitud_min_msnm"], f["altitud_max_msnm"]): f for f in vigentes}
    enviados = {(r["altitud_min_msnm"], r["altitud_max_msnm"]) for r in rangos}

    def vigente_en(altitud: int):
        return next((f for f in vigentes if f["altitud_min_msnm"] <= altitud <= f["altitud_max_msnm"]), None)

    cambios, nuevas, cerrar = [], [], []
    for i, r in enumerate(rangos):
        campo = f"rangos.{i}"
        clave = (r["altitud_min_msnm"], r["altitud_max_msnm"])
        referencia_previa = por_rango.get(clave) or vigente_en(r["altitud_min_msnm"])
        if referencia_previa is not None and abs(r["ajuste_g_dl"] - referencia_previa["ajuste_g_dl"]) > R.CAMBIO_AJUSTE_ADVERTENCIA:
            rev.advertencia(f"{campo}.ajuste_g_dl", f"{clave[0]} a {clave[1]} m.s.n.m.: el ajuste pasa de "
                            f"{_texto(referencia_previa['ajuste_g_dl'])} a {_texto(r['ajuste_g_dl'])} g/dL "
                            f"(más de {R.CAMBIO_AJUSTE_ADVERTENCIA} g/dL)")
        previo = por_rango.get(clave)
        if previo is None:  # rango nuevo (la tabla cambió de forma)
            if bool(r.get("verificado")) and not e.referencia:
                rev.error("referencia", "es obligatoria cuando un valor queda verificado contra la norma")
            if referencia_previa is None and e.id_documento is None:
                rev.error("id_documento", f"es obligatorio para el rango nuevo {clave[0]} a {clave[1]} m.s.n.m.")
            nuevas.append((referencia_previa, r))
            cambios.append({"elemento": f"{clave[0]} a {clave[1]} m.s.n.m.", "antes": None,
                            "despues": {"ajuste_g_dl": _num(r["ajuste_g_dl"]), "verificado": bool(r.get("verificado"))}})
            continue
        iguales = previo["ajuste_g_dl"] == r["ajuste_g_dl"]
        if _verificacion(rev, campo, previo["verificado"], bool(r.get("verificado")), iguales, e):
            cerrar.append(previo["id_ajuste"])
            nuevas.append((previo, r))
            cambios.append({"elemento": f"{clave[0]} a {clave[1]} m.s.n.m.",
                            "antes": {"ajuste_g_dl": _num(previo["ajuste_g_dl"]), "verificado": previo["verificado"]},
                            "despues": {"ajuste_g_dl": _num(r["ajuste_g_dl"]), "verificado": bool(r.get("verificado"))}})
    for clave, f in por_rango.items():  # rangos vigentes que ya no están en la tabla
        if clave not in enviados:
            cerrar.append(f["id_ajuste"])
            cambios.append({"elemento": f"{clave[0]} a {clave[1]} m.s.n.m.",
                            "antes": {"ajuste_g_dl": _num(f["ajuste_g_dl"]), "verificado": f["verificado"]}, "despues": None})
    _confirmar(rev, e)
    if not cambios:
        raise ErrorEdicion(422, MENSAJE_SIN_CAMBIOS, "SIN_CAMBIOS")

    cerrados = _cerrar(sesion, grupo, cerrar)
    creados = [insertar_ajuste(sesion, e, previo, r) for previo, r in nuevas]
    resumen = _evento(sesion, grupo, e, cerrados, sorted(creados), cambios, rev.advertencias)
    return {"grupo": lectura.ajuste_altitud(sesion), "resumen": resumen}


def insertar_ajuste(sesion: Session, e: Edicion, previo, r: dict) -> int:
    documento = e.id_documento or (previo["id_documento"] if previo is not None else None)
    return sesion.execute(text(
        """INSERT INTO configuracion.ajuste_altitud
             (id_documento, altitud_min_msnm, altitud_max_msnm, ajuste_g_dl, vigente_desde, modificado_por,
              motivo_cambio, referencia, verificado)
           VALUES (CAST(:doc AS uuid), :amin, :amax, :aj, now(), CAST(:u AS uuid), :motivo, :ref, :ver)
           RETURNING id_ajuste"""),
        {"doc": documento, "amin": r["altitud_min_msnm"], "amax": r["altitud_max_msnm"], "aj": r["ajuste_g_dl"],
         "u": e.id_usuario, "motivo": e.motivo_cambio, "ref": e.referencia, "ver": bool(r.get("verificado"))}).scalar_one()


# ---------------------------------------------------------------------------
# Vigencia del tamizaje
# ---------------------------------------------------------------------------
def editar_vigencia(sesion: Session, e: Edicion, valor: int, verificado: bool) -> dict:
    grupo = "vigencia_tamizaje"
    _bloquear(sesion, grupo)
    filas = lectura._parametros(sesion, [lectura.CLAVE_VIGENCIA])
    if not filas:
        raise LookupError(f"No hay valor vigente para {lectura.CLAVE_VIGENCIA}")
    previo = filas[0]
    _comprobar_version(e.version, lectura.version_de(grupo, [previo["id_parametro"]]))
    rev = Revision()
    _comprobar_documento(sesion, e, rev)
    minimo = max(R.VIGENCIA_MIN_DIAS, int(previo["valor_minimo"]) if previo["valor_minimo"] is not None else R.VIGENCIA_MIN_DIAS)
    maximo = min(R.VIGENCIA_MAX_DIAS, int(previo["valor_maximo"]) if previo["valor_maximo"] is not None else R.VIGENCIA_MAX_DIAS)
    if not minimo <= valor <= maximo:
        rev.error("valor", f"debe ser un número entero de días entre {minimo} y {maximo}")
    elif valor > R.VIGENCIA_ADVERTENCIA_DIAS:
        rev.advertencia("valor", f"una vigencia de {valor} días supera los {R.VIGENCIA_ADVERTENCIA_DIAS} días: "
                        "un tamizaje viejo se seguiría usando para evaluar")
    iguales = str(valor) == previo["valor"]
    cambia = _verificacion(rev, "valor", previo["verificado"], verificado, iguales, e)
    _confirmar(rev, e)
    if not cambia:
        raise ErrorEdicion(422, MENSAJE_SIN_CAMBIOS, "SIN_CAMBIOS")

    cerrados = _cerrar(sesion, grupo, [previo["id_parametro"]])
    nuevo = insertar_parametro(sesion, e, previo, str(valor), verificado)
    cambios = [{"elemento": lectura.CLAVE_VIGENCIA, "antes": {"valor": previo["valor"], "verificado": previo["verificado"]},
                "despues": {"valor": str(valor), "verificado": verificado}}]
    resumen = _evento(sesion, grupo, e, cerrados, [nuevo], cambios, rev.advertencias)
    return {"grupo": lectura.vigencia_tamizaje(sesion), "resumen": resumen}


def insertar_parametro(sesion: Session, e: Edicion, previo, valor: str, verificado: bool) -> int:
    return sesion.execute(text(
        """INSERT INTO configuracion.parametro_sistema
             (clave, valor, tipo_dato, valor_minimo, valor_maximo, descripcion, vigente_desde, modificado_por,
              motivo_cambio, referencia, verificado, id_documento)
           VALUES (:clave, :valor, :tipo, :vmin, :vmax, :descr, now(), CAST(:u AS uuid), :motivo, :ref, :ver,
                   CAST(:doc AS uuid))
           RETURNING id_parametro"""),
        {"clave": previo["clave"], "valor": valor, "tipo": previo["tipo_dato"], "vmin": previo["valor_minimo"],
         "vmax": previo["valor_maximo"], "descr": previo["descripcion"], "u": e.id_usuario, "motivo": e.motivo_cambio,
         "ref": e.referencia, "ver": verificado, "doc": e.id_documento or previo["id_documento"]}).scalar_one()
