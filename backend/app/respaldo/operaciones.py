"""Operaciones del respaldo: crear, restaurar, verificar (contra PostgreSQL), comparar y descartar.

Formato de un respaldo (carpeta respaldo_AAAAMMDD_HHMMSS, hora de Perú):
- coleccion.json: nombre y metadatos de la colección (la distancia coseno es esencial).
- vectores.jsonl: un registro por línea (id, vector, texto, metadatos), ordenado por id. Los floats
  se escriben con la representación exacta de Python: el archivo guarda exactamente lo que devolvió
  ChromaDB. Al restaurar en una colección con distancia coseno, ChromaDB vuelve a normalizar cada
  vector en float32 y algunos componentes cambian en el último dígito; por eso los vectores se
  comparan con TOLERANCIA_VECTOR, y los ids, textos y metadatos, exactos.
- guias_cargadas/: los PDF cargados desde M11 (volumen datos_guias_cargadas).
- manifiesto.json: fecha, versiones, modelo, conteos y la lista de archivos con tamaño y SHA-256.
- manifiesto.json.sha256: el SHA-256 del manifiesto.

Las funciones reciben el servidor de colecciones (ServidorChroma o ServidorMemoria), el destino y
la fuente de PostgreSQL como parámetros, para poder probarlas sin ChromaDB real."""
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.fechas import ZONA_PERU
from app.core.vectores import COLECCION, ESPACIO, ErrorColeccion, RegistroVector
from app.respaldo.destinos import (HUELLA_MANIFIESTO, MANIFIESTO, Destino, ErrorRespaldo, ruta_segura, sha256_archivo,
                                   sha256_bytes)

FORMATO = 1
ARCHIVO_COLECCION = "coleccion.json"
ARCHIVO_VECTORES = "vectores.jsonl"
CARPETA_GUIAS = "guias_cargadas"
LOTE = 64
# Tolerancia absoluta por componente al comparar un vector exportado con uno restaurado (o dos
# colecciones). Con distancia coseno, ChromaDB normaliza cada vector al guardarlo, en float32: aunque
# los vectores ya sean unitarios, el último dígito de algunos componentes cambia (hasta unos 3e-8 en
# bge-m3 de 1024 dimensiones). 1e-6 cubre ese redondeo con margen y sigue detectando cualquier cambio
# real; no altera los resultados de las consultas. Ids, textos y metadatos se comparan exactos.
TOLERANCIA_VECTOR = 1e-6
DIR_APP = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _linea(r: RegistroVector) -> str:
    return json.dumps({"id": r.id, "vector": r.vector, "texto": r.texto, "metadatos": r.metadatos},
                      ensure_ascii=False, allow_nan=False, sort_keys=True)


def _registro(linea: str) -> RegistroVector:
    d = json.loads(linea)
    return RegistroVector(d["id"], d["vector"], d["texto"], d["metadatos"])


def leer_vectores(carpeta: Path) -> list[RegistroVector]:
    with (carpeta / ARCHIVO_VECTORES).open(encoding="utf-8") as f:
        return [_registro(linea) for linea in f if linea.strip()]


def version_codigo() -> str:
    """CDSS_VERSION_CODIGO (por ejemplo, la etiqueta de git del despliegue) o, fuera de Docker, git."""
    valor = os.environ.get("CDSS_VERSION_CODIGO", "").strip()
    if valor:
        return valor
    try:
        r = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=DIR_APP, capture_output=True,
                           text=True, timeout=5)
        return r.stdout.strip() or "sin etiqueta"
    except (OSError, subprocess.SubprocessError):
        return "sin etiqueta"


def huella_codigo() -> str:
    """SHA-256 de los archivos .py de backend/app (identifica el código aunque no haya git)."""
    h = hashlib.sha256()
    for ruta in sorted(DIR_APP.rglob("*.py")):
        h.update(ruta.relative_to(DIR_APP).as_posix().encode())
        h.update(b"\0")
        h.update(ruta.read_bytes())
    return h.hexdigest()


def diferencia_vector(a: list[float], b: list[float]) -> float | None:
    """Mayor diferencia absoluta entre componentes; None si las longitudes no coinciden."""
    if len(a) != len(b):
        return None
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0)


def formato_diferencia(d: float) -> str:
    return "0" if d == 0 else f"{d:.1e}"


def _todos(almacen) -> list[RegistroVector]:
    ids = almacen.ids()
    registros: list[RegistroVector] = []
    for i in range(0, len(ids), LOTE):
        registros.extend(almacen.obtener(ids[i:i + LOTE]))
    return registros


# ---------------------------------------------------------------------------
# Crear
# ---------------------------------------------------------------------------
@dataclass
class ResultadoCreacion:
    nombre: str
    vectores: int
    vigentes: int
    guias: int
    forzado: bool
    eliminados: list[str] = field(default_factory=list)


def crear(servidor, destino: Destino, fuente, *, dir_guias: Path | None, coleccion: str = COLECCION,
          forzar: bool = False, conservar: int = 7, ahora: datetime | None = None) -> ResultadoCreacion:
    if conservar < 1:
        raise ErrorRespaldo("--conservar debe ser 1 o más")
    activos = fuente.trabajos_activos()
    if activos and not forzar:
        raise ErrorRespaldo(f"Hay {activos} trabajos de indexación pendientes o en curso: el respaldo no sería "
                            "una instantánea coherente. Espere a que terminen (pantalla M11) o use --forzar")
    almacen = servidor.abrir(coleccion)
    if almacen is None:
        raise ErrorRespaldo(f"La colección {coleccion} no existe en ChromaDB")

    ahora = ahora or datetime.now(ZONA_PERU)
    nombre = f"respaldo_{ahora.astimezone(ZONA_PERU):%Y%m%d_%H%M%S}"
    carpeta = destino.carpeta_nueva(nombre)
    try:
        resultado = _escribir(carpeta, nombre, servidor, almacen, fuente, dir_guias, coleccion, activos, forzar, ahora)
        verificar_carpeta(carpeta)  # lo escrito se puede leer y coincide con el manifiesto
        destino.publicar(nombre, carpeta)
    except BaseException:
        destino.descartar_incompleto(nombre, carpeta)
        raise
    # Retención: solo después de un respaldo completo, y solo respaldos de este mismo destino.
    nombres = destino.listar()
    for antiguo in sorted(nombres, reverse=True)[conservar:]:
        if antiguo != nombre:
            destino.borrar(antiguo)
            resultado.eliminados.append(antiguo)
    fuente.auditar("RESPALDO_CREADO", nombre, {
        "coleccion": coleccion, "vectores": resultado.vectores, "vigentes": resultado.vigentes,
        "guias": resultado.guias, "destino": destino.tipo, "forzado": forzar, "trabajos_activos": activos,
        "respaldos_eliminados": len(resultado.eliminados)})
    return resultado


def _escribir(carpeta: Path, nombre: str, servidor, almacen, fuente, dir_guias: Path | None, coleccion: str,
              activos: int, forzar: bool, ahora: datetime) -> ResultadoCreacion:
    metadatos_coleccion = almacen.metadatos_coleccion
    (carpeta / ARCHIVO_COLECCION).write_text(
        json.dumps({"nombre": coleccion, "metadatos": metadatos_coleccion}, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n", encoding="utf-8")

    ids = almacen.ids()
    vigentes = 0
    por_nivel: Counter = Counter()
    with (carpeta / ARCHIVO_VECTORES).open("w", encoding="utf-8", newline="\n") as f:
        for i in range(0, len(ids), LOTE):
            parte = almacen.obtener(ids[i:i + LOTE])
            if len(parte) != len(ids[i:i + LOTE]):
                raise ErrorRespaldo("La colección cambió durante el respaldo (faltan vectores); vuelva a intentarlo")
            for r in parte:
                vigentes += r.metadatos.get("vigente") is True
                por_nivel[str(r.metadatos.get("nivel"))] += 1
                f.write(_linea(r) + "\n")

    guias: list[dict] = []
    if dir_guias is not None and dir_guias.is_dir():
        destino_guias = carpeta / CARPETA_GUIAS
        destino_guias.mkdir()
        for ruta in sorted(p for p in dir_guias.iterdir() if p.is_file() and not p.is_symlink()):
            shutil.copyfile(ruta, destino_guias / ruta.name)
            if sha256_archivo(destino_guias / ruta.name) != sha256_archivo(ruta):
                raise ErrorRespaldo(f"La guía {ruta.name} cambió mientras se copiaba; vuelva a intentarlo")
            guias.append({"archivo": ruta.name, "sha256": sha256_archivo(ruta)})

    archivos = [{"ruta": p.relative_to(carpeta).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_archivo(p)}
                for p in sorted(carpeta.rglob("*")) if p.is_file()]
    manifiesto = {
        "formato": FORMATO,
        "nombre": nombre,
        "fecha": ahora.astimezone(ZONA_PERU).isoformat(timespec="seconds"),
        "version_codigo": version_codigo(),
        "huella_codigo": huella_codigo(),
        "version_chromadb": servidor.version(),
        "modelo_embeddings": fuente.modelos_embedding(),
        "coleccion": {"nombre": coleccion, "metadatos": metadatos_coleccion},
        "vectores": len(ids),
        "vectores_vigentes": vigentes,
        "vectores_por_nivel": dict(sorted(por_nivel.items())),
        "guias_cargadas": guias,
        "forzado": forzar,
        "trabajos_activos": activos,
        "archivos": archivos,
    }
    datos = (json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (carpeta / MANIFIESTO).write_bytes(datos)
    (carpeta / HUELLA_MANIFIESTO).write_text(f"{sha256_bytes(datos)}  {MANIFIESTO}\n", encoding="utf-8")
    return ResultadoCreacion(nombre, len(ids), vigentes, len(guias), forzar)


# ---------------------------------------------------------------------------
# Comprobar una carpeta de respaldo (antes de restaurar)
# ---------------------------------------------------------------------------
def verificar_carpeta(carpeta: Path) -> dict:
    """Comprueba el SHA-256 del manifiesto y el tamaño y el SHA-256 de cada archivo, y que los vectores
    coincidan con el manifiesto. Devuelve el manifiesto. No escribe nada."""
    manifiesto_ruta, huella_ruta = carpeta / MANIFIESTO, carpeta / HUELLA_MANIFIESTO
    if not manifiesto_ruta.is_file() or not huella_ruta.is_file():
        raise ErrorRespaldo(f"Faltan {MANIFIESTO} o {HUELLA_MANIFIESTO} en el respaldo")
    datos = manifiesto_ruta.read_bytes()
    huella = huella_ruta.read_text(encoding="utf-8").split()
    if not huella or huella[0] != sha256_bytes(datos):
        raise ErrorRespaldo("El manifiesto no coincide con su SHA-256: el respaldo fue modificado")
    manifiesto = json.loads(datos)
    if manifiesto.get("formato") != FORMATO:
        raise ErrorRespaldo(f"Formato de respaldo desconocido: {manifiesto.get('formato')}")
    listados = set()
    for archivo in manifiesto["archivos"]:
        ruta = ruta_segura(carpeta, archivo["ruta"])
        listados.add(archivo["ruta"])
        if not ruta.is_file():
            raise ErrorRespaldo(f"Falta el archivo {archivo['ruta']} del respaldo")
        if ruta.stat().st_size != archivo["bytes"] or sha256_archivo(ruta) != archivo["sha256"]:
            raise ErrorRespaldo(f"El archivo {archivo['ruta']} no coincide con el manifiesto (tamaño o SHA-256): "
                                "el respaldo fue modificado")
    for obligatorio in (ARCHIVO_COLECCION, ARCHIVO_VECTORES):
        if obligatorio not in listados:
            raise ErrorRespaldo(f"El manifiesto no incluye {obligatorio}")
    ids = [r.id for r in leer_vectores(carpeta)]
    if len(ids) != manifiesto["vectores"] or len(set(ids)) != len(ids):
        raise ErrorRespaldo("El número de vectores no coincide con el manifiesto")
    return manifiesto


# ---------------------------------------------------------------------------
# Restaurar
# ---------------------------------------------------------------------------
@dataclass
class ResultadoRestauracion:
    respaldo: str
    coleccion: str
    vectores: int
    guias_copiadas: list[str] = field(default_factory=list)
    guias_existentes: list[str] = field(default_factory=list)
    guias_distintas: list[str] = field(default_factory=list)
    verificacion: "ResultadoVerificacion | None" = None
    # Mayor diferencia por componente entre los vectores del respaldo y los restaurados
    diferencia_maxima: float = 0.0


def restaurar(servidor, destino: Destino, fuente, nombre: str, *, coleccion: str = COLECCION,
              con_guias: bool = False, dir_guias: Path | None = None) -> ResultadoRestauracion:
    carpeta = destino.obtener(nombre)
    manifiesto = verificar_carpeta(carpeta)  # si algo no coincide, se niega antes de escribir nada
    original = json.loads((carpeta / ARCHIVO_COLECCION).read_text(encoding="utf-8"))
    metadatos = original["metadatos"]
    if con_guias and (dir_guias is None or not dir_guias.is_dir()):
        raise ErrorRespaldo("--con-guias necesita la carpeta de las guías cargadas (volumen datos_guias_cargadas)")

    existente = servidor.abrir(coleccion)
    if existente is not None:
        if existente.contar() > 0:
            raise ErrorRespaldo(f"La colección {coleccion} ya tiene {existente.contar()} vectores: no se sobrescribe "
                                "ni se borra. Restaure en otro nombre con --coleccion "
                                "(por ejemplo, guias_clinicas_prueba_restauracion)")
        if existente.metadatos_coleccion != metadatos:
            raise ErrorRespaldo(f"La colección {coleccion} existe vacía pero con otros metadatos "
                                f"({existente.metadatos_coleccion}); el respaldo necesita {metadatos}")
        almacen = existente
    else:
        try:
            almacen = servidor.crear(coleccion, metadatos)
        except ErrorColeccion as e:
            raise ErrorRespaldo(str(e)) from e

    registros = leer_vectores(carpeta)
    for i in range(0, len(registros), LOTE):
        almacen.agregar(registros[i:i + LOTE])
    # Comprobación posterior: ids, textos y metadatos exactos; vectores dentro de TOLERANCIA_VECTOR (la
    # normalización de ChromaDB con coseno cambia el último dígito de algunos componentes); la distancia
    # de la colección, la original.
    aviso = (f"La colección {coleccion} ya quedó escrita y no se borra sola; si es una colección de prueba, "
             f"límpiela con descartar-coleccion {coleccion}")
    restaurados = {r.id: r for r in _todos(almacen)}
    if almacen.metadatos_coleccion.get(ESPACIO) != metadatos.get(ESPACIO):
        raise ErrorRespaldo(f"La colección restaurada no quedó con la distancia del respaldo. {aviso}")
    distintos, diferencia_maxima = [], 0.0
    for r in registros:
        otro = restaurados.get(r.id)
        d = None if otro is None else diferencia_vector(r.vector, otro.vector)
        if otro is None or otro.texto != r.texto or otro.metadatos != r.metadatos or d is None or d > TOLERANCIA_VECTOR:
            distintos.append(r.id)
        else:
            diferencia_maxima = max(diferencia_maxima, d)
    if len(restaurados) != len(registros) or distintos:
        raise ErrorRespaldo(f"La colección restaurada no coincide con el respaldo ({len(distintos)} vectores distintos "
                            f"en ids, textos, metadatos o vectores fuera de la tolerancia de {TOLERANCIA_VECTOR:g}). "
                            f"{aviso}")

    resultado = ResultadoRestauracion(manifiesto["nombre"], coleccion, len(registros))
    resultado.diferencia_maxima = diferencia_maxima
    if con_guias:
        _restaurar_guias(carpeta, manifiesto, dir_guias, resultado)
    resultado.verificacion = verificar(servidor, fuente, coleccion)
    fuente.auditar("RESPALDO_RESTAURADO", manifiesto["nombre"], {
        "coleccion": coleccion, "vectores": len(registros), "guias_copiadas": len(resultado.guias_copiadas),
        "guias_existentes": len(resultado.guias_existentes), "guias_distintas": len(resultado.guias_distintas),
        "verificacion": "ok" if resultado.verificacion.ok else "con_diferencias"})
    return resultado


def _restaurar_guias(carpeta: Path, manifiesto: dict, dir_guias: Path, resultado: ResultadoRestauracion) -> None:
    """Copia solo las guías que faltan; nunca sobrescribe un archivo distinto (lo informa)."""
    for guia in manifiesto["guias_cargadas"]:
        origen = ruta_segura(carpeta / CARPETA_GUIAS, guia["archivo"])
        destino = ruta_segura(dir_guias, guia["archivo"])
        if destino.exists():
            (resultado.guias_existentes if sha256_archivo(destino) == guia["sha256"]
             else resultado.guias_distintas).append(guia["archivo"])
            continue
        temporal = destino.with_name(f".{destino.name}.restaurando")
        shutil.copyfile(origen, temporal)
        if sha256_archivo(temporal) != guia["sha256"]:
            temporal.unlink(missing_ok=True)
            raise ErrorRespaldo(f"La guía {guia['archivo']} no se copió bien (SHA-256 distinto)")
        os.replace(temporal, destino)
        resultado.guias_copiadas.append(guia["archivo"])


# ---------------------------------------------------------------------------
# Verificar contra PostgreSQL (solo lectura)
# ---------------------------------------------------------------------------
@dataclass
class ResultadoVerificacion:
    coleccion: str
    existe: bool = True
    distancia: str | None = None
    vectores: int = 0
    vigentes: int = 0
    por_nivel: dict = field(default_factory=dict)
    por_estado: dict = field(default_factory=dict)
    faltantes: list[str] = field(default_factory=list)
    huerfanos: list[str] = field(default_factory=list)
    vigencia_distinta: list[str] = field(default_factory=list)
    estado_distinto: list[str] = field(default_factory=list)
    nivel_distinto: list[str] = field(default_factory=list)
    documento_distinto: list[str] = field(default_factory=list)

    @property
    def problemas(self) -> list[str]:
        if not self.existe:
            return [f"la colección {self.coleccion} no existe"]
        salida = []
        if self.distancia != "cosine":
            salida.append(f"distancia {self.distancia!r} en lugar de 'cosine'")
        for texto, lista in (("vectores faltantes (en PostgreSQL y no en la colección)", self.faltantes),
                             ("vectores huérfanos (en la colección y no en PostgreSQL)", self.huerfanos),
                             ("vectores con la vigencia distinta de fragmento.vigente", self.vigencia_distinta),
                             ("vectores con estado_documento distinto de documento_fuente", self.estado_distinto),
                             ("vectores con el nivel distinto de documento_fuente", self.nivel_distinto),
                             ("vectores con otro id_documento", self.documento_distinto)):
            if lista:
                salida.append(f"{len(lista)} {texto}: {', '.join(lista[:5])}{' …' if len(lista) > 5 else ''}")
        return salida

    @property
    def ok(self) -> bool:
        return not self.problemas


def verificar(servidor, fuente, coleccion: str = COLECCION) -> ResultadoVerificacion:
    resultado = ResultadoVerificacion(coleccion)
    almacen = servidor.abrir(coleccion)
    if almacen is None:
        resultado.existe = False
        return resultado
    resultado.distancia = almacen.metadatos_coleccion.get(ESPACIO)
    esperados = fuente.fragmentos_esperados()
    registros = {r.id: r for r in _todos(almacen)}
    resultado.vectores = len(registros)
    resultado.vigentes = sum(r.metadatos.get("vigente") is True for r in registros.values())
    resultado.por_nivel = dict(sorted(Counter(str(r.metadatos.get("nivel")) for r in registros.values()).items()))
    resultado.por_estado = dict(sorted(Counter(str(r.metadatos.get("estado_documento"))
                                               for r in registros.values()).items()))
    resultado.faltantes = sorted(set(esperados) - set(registros))
    resultado.huerfanos = sorted(set(registros) - set(esperados))
    for id_, esperado in sorted(esperados.items()):
        r = registros.get(id_)
        if r is None:
            continue
        m = r.metadatos
        if m.get("vigente") is not esperado.vigente:
            resultado.vigencia_distinta.append(id_)
        if m.get("estado_documento") != esperado.estado_documento:
            resultado.estado_distinto.append(id_)
        if m.get("nivel") != esperado.nivel:
            resultado.nivel_distinto.append(id_)
        if m.get("id_documento") != esperado.id_documento:
            resultado.documento_distinto.append(id_)
    return resultado


# ---------------------------------------------------------------------------
# Comparar dos colecciones
# ---------------------------------------------------------------------------
@dataclass
class ResultadoComparacion:
    vectores_a: int
    vectores_b: int
    diferencias: list[str] = field(default_factory=list)
    consultas: int = 0
    # Mayor diferencia por componente entre los vectores de los ids comunes que están dentro de la tolerancia
    diferencia_maxima: float = 0.0

    @property
    def identicas(self) -> bool:
        return not self.diferencias


def comparar(servidor, coleccion_a: str, coleccion_b: str, consultas: int = 5, n: int = 5) -> ResultadoComparacion:
    a, b = servidor.abrir(coleccion_a), servidor.abrir(coleccion_b)
    for nombre, almacen in ((coleccion_a, a), (coleccion_b, b)):
        if almacen is None:
            raise ErrorRespaldo(f"La colección {nombre} no existe")
    registros_a = {r.id: r for r in _todos(a)}
    registros_b = {r.id: r for r in _todos(b)}
    resultado = ResultadoComparacion(len(registros_a), len(registros_b))
    if a.metadatos_coleccion != b.metadatos_coleccion:
        resultado.diferencias.append(f"metadatos de la colección distintos: {a.metadatos_coleccion} y "
                                     f"{b.metadatos_coleccion}")
    solo_a, solo_b = sorted(set(registros_a) - set(registros_b)), sorted(set(registros_b) - set(registros_a))
    if solo_a:
        resultado.diferencias.append(f"{len(solo_a)} ids solo en {coleccion_a}")
    if solo_b:
        resultado.diferencias.append(f"{len(solo_b)} ids solo en {coleccion_b}")
    comunes = sorted(set(registros_a) & set(registros_b))
    # Ids, textos y metadatos exactos; vectores dentro de TOLERANCIA_VECTOR (normalización de ChromaDB).
    fuera = []
    for i in comunes:
        d = diferencia_vector(registros_a[i].vector, registros_b[i].vector)
        if d is None or d > TOLERANCIA_VECTOR:
            fuera.append(i)
        else:
            resultado.diferencia_maxima = max(resultado.diferencia_maxima, d)
    if fuera:
        resultado.diferencias.append(f"{len(fuera)} vectores con vector distinto, fuera de la tolerancia de "
                                     f"{TOLERANCIA_VECTOR:g} (por ejemplo {fuera[0]})")
    for campo in ("texto", "metadatos"):
        distintos = [i for i in comunes if getattr(registros_a[i], campo) != getattr(registros_b[i], campo)]
        if distintos:
            resultado.diferencias.append(f"{len(distintos)} vectores con {campo} distinto (por ejemplo {distintos[0]})")
    # Consultas con vectores guardados, repartidos a lo largo de los ids ordenados.
    ids = sorted(registros_a)
    if ids:
        elegidos = sorted({ids[round(k * (len(ids) - 1) / max(consultas - 1, 1))] for k in range(consultas)})
        for id_ in elegidos:
            vector = registros_a[id_].vector
            primeros_a = [i for i, _ in a.consultar(vector, min(n, len(registros_a)))]
            primeros_b = [i for i, _ in b.consultar(vector, min(n, len(registros_b)))]
            resultado.consultas += 1
            if primeros_a != primeros_b:
                resultado.diferencias.append(f"la consulta con el vector {id_} devuelve otros resultados: "
                                             f"{primeros_a} y {primeros_b}")
    return resultado


# ---------------------------------------------------------------------------
# Descartar una colección de prueba
# ---------------------------------------------------------------------------
def descartar_coleccion(servidor, nombre: str) -> None:
    """Borra una colección de prueba. La barrera del nombre está en el servidor (exigir_coleccion_de_prueba)."""
    try:
        servidor.borrar(nombre)
    except ErrorColeccion as e:
        raise ErrorRespaldo(str(e)) from e
