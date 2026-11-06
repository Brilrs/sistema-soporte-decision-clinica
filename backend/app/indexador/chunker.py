"""Fragmentación de los segmentos: objetivo de 500 tokens, máximo de 800 y
solapamiento de 80 (parámetros del sistema), con cortes en numerales y títulos,
nunca a mitad de frase. Cada tabla queda entera en un solo fragmento, salvo la que
supera el máximo del servicio de modelos: esa se parte por grupos de filas y cada
parte repite el título y el encabezado de columnas."""
import re
from dataclasses import dataclass, field
from datetime import date

from app.indexador.segmentacion import Segmento, TextoDocumento
from app.indexador.servicios import Tokenizador

_ROMANO = re.compile(r"^[\"“']?((?:I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,:]{3,90})$")
_NUMERAL = re.compile(r"^[\"“']?(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+([A-ZÁÉÍÓÚÑ¿][^\n]{2,200})")
_LITERAL = re.compile(r"^([A-H])\.\s+([A-ZÁÉÍÓÚÑ][^\n]{2,150})")
_ITEM = re.compile(r"^(\d{1,2})\.\s+([A-ZÁÉÍÓÚÑ][^\n]{2,150})")
_TABLA = re.compile(r"^(?:Tabla|Table)\s*(?:N|No)?\s*[°ºo’'”\".]*\s*\d+\s*(?:[.:]\s+\S.*)?$", re.IGNORECASE)
_FIN_TABLA = re.compile(r"^(?:Fuente|Source|Nota|Note|\(\s*[*•]\s*\))", re.IGNORECASE)
_VINETA = re.compile(r"^(?:[-•*·]\s|\(\.\.\.\))")
_FRASE = re.compile(r"(?<=[.;:!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"“(•\-\d])")
MAX_LINEAS_TABLA = 70
NIVEL_CORTE = 3
MIN_TOKENS_CORTE = 40
# Máximo de tokens por texto del servicio modelos (MODELOS_MAX_LONGITUD_EMBEDDING): una tabla
# más larga se parte por grupos de filas para que el embedding cubra todo su contenido.
LIMITE_TABLA = 1024
_SEPARADOR_MD = re.compile(r"^\|\s*:?-{3,}")


@dataclass
class Fragmento:
    texto: str
    seccion: str | None
    pagina_inicio: int
    pagina_fin: int
    tipo_contenido: str
    fuente_texto: str
    vigente: bool
    motivo_exclusion: str | None
    id_documento_modificatorio: str | None
    verificado: bool
    fecha_verificacion: date | None
    transcripcion: str | None = None
    modificacion: int | None = None
    numero_tokens: int = 0
    orden: int = 0


@dataclass
class _Unidad:
    texto: str
    inicio: int
    es_tabla: bool = False
    corte_antes: int = 0
    nuevo_parrafo: bool = True
    titulo_tabla: str | None = None


@dataclass
class Avisos:
    mensajes: list[str] = field(default_factory=list)


def _titulo(texto: str, largo: int = 90) -> str:
    texto = texto.strip().rstrip(":")
    corte = re.search(r"(?<=\w)\.\s", texto)
    if corte and corte.start() < largo:
        texto = texto[:corte.start() + 1]
    return texto if len(texto) <= largo else texto[:largo].rsplit(" ", 1)[0] + "..."


def encabezado(linea: str) -> tuple[int, str] | None:
    """Nivel y título de una línea que abre una sección, o None."""
    linea = linea.strip()
    if m := _ROMANO.match(linea):
        return 1, m.group(1).strip()
    if m := _NUMERAL.match(linea):
        return 1 + m.group(1).count(".") + 1, f"{m.group(1)}. {_titulo(m.group(2))}"
    if m := _LITERAL.match(linea):
        return 5, f"{m.group(1)}. {_titulo(m.group(2))}"
    if m := _ITEM.match(linea):
        return 6, f"{m.group(1)}. {_titulo(m.group(2))}"
    return None


class MapaSecciones:
    """Ruta de títulos vigente en cada posición del texto del documento."""

    def __init__(self, doc: TextoDocumento):
        self._marcas: list[tuple[int, str]] = []
        pila: dict[int, str] = {}
        pos = 0
        for linea in doc.texto.split("\n"):
            e = encabezado(linea)
            if e:
                nivel, titulo = e
                pila = {k: v for k, v in pila.items() if k < nivel}
                pila[nivel] = titulo
                ruta = [pila[k] for k in sorted(pila) if k > 1] or [pila[k] for k in sorted(pila)]
                self._marcas.append((pos, " > ".join(ruta[-3:])))
            pos += len(linea) + 1

    def en(self, posicion: int) -> str | None:
        actual = None
        for pos, ruta in self._marcas:
            if pos > posicion:
                break
            actual = ruta
        return actual


def _unidades(segmento: Segmento) -> list[_Unidad]:
    """Divide el texto en frases y tablas, con la posición de cada una en el documento."""
    lineas, pos = [], segmento.inicio
    for linea in segmento.texto.split("\n"):
        lineas.append((linea.strip(), pos))
        pos += len(linea) + 1

    unidades: list[_Unidad] = []
    parrafo: list[tuple[str, int]] = []
    corte_pendiente = 0

    def cerrar_parrafo() -> None:
        nonlocal parrafo, corte_pendiente
        if not parrafo:
            return
        texto = " ".join(l for l, _ in parrafo)
        desplazamientos, acumulado = [], 0
        for l, p in parrafo:
            desplazamientos.append((acumulado, p))
            acumulado += len(l) + 1
        inicio_frase = 0
        frases = _FRASE.split(texto)
        for i, frase in enumerate(frases):
            origen = max(p for d, p in desplazamientos if d <= inicio_frase)
            unidades.append(_Unidad(frase, origen, corte_antes=corte_pendiente if i == 0 else 0, nuevo_parrafo=i == 0))
            inicio_frase += len(frase) + 1
        parrafo = []
        corte_pendiente = 0

    i = 0
    while i < len(lineas):
        linea, p = lineas[i]
        if not linea:
            i += 1
            continue
        if _TABLA.match(linea):
            cerrar_parrafo()
            fin = i + 1
            while fin < len(lineas) and fin - i < MAX_LINEAS_TABLA:
                siguiente = lineas[fin][0]
                if _FIN_TABLA.match(siguiente):
                    fin += 1
                    while fin < len(lineas) and lineas[fin][0] and not encabezado(lineas[fin][0]) \
                            and not _TABLA.match(lineas[fin][0]) and re.match(r"^[a-e]\)|^\(\*\)|^\(•\)", lineas[fin][0]):
                        fin += 1
                    break
                if encabezado(siguiente) or _TABLA.match(siguiente):
                    break
                fin += 1
            titulo = " ".join(l for l, _ in lineas[i:i + 2])[:150]
            unidades.append(_Unidad("\n".join(l for l, _ in lineas[i:fin]), p, es_tabla=True, titulo_tabla=titulo))
            i = fin
            continue
        if e := encabezado(linea):
            cerrar_parrafo()
            corte_pendiente = e[0]
        elif _VINETA.match(linea):
            cerrar_parrafo()
        parrafo.append((linea, p))
        i += 1
    cerrar_parrafo()
    return unidades


def _partir(texto: str, maximo_palabras: int) -> list[str]:
    palabras = texto.split()
    return [" ".join(palabras[i:i + maximo_palabras]) for i in range(0, len(palabras), maximo_palabras)]


def partir_tabla(texto: str, tokenizador: Tokenizador, limite: int, prefijo: str = "") -> list[str]:
    """Divide una tabla en partes de a lo sumo `limite` tokens, por grupos de filas.
    Cada parte repite el prefijo, el título y el encabezado de columnas; las notas
    y la fuente van en la última parte. Si cabe entera, la devuelve igual."""
    if tokenizador.contar([prefijo + texto])[0] <= limite:
        return [texto]
    lineas = texto.split("\n")
    separador = next((i for i, l in enumerate(lineas) if _SEPARADOR_MD.match(l.strip())), None)
    if separador is not None:
        cabecera = lineas[:separador + 1]
        resto = lineas[separador + 1:]
        n_filas = next((i for i, l in enumerate(resto) if l.strip() and not l.strip().startswith("|")), len(resto))
    else:
        cabecera = lineas[:2]
        resto = lineas[2:]
        n_filas = next((i for i, l in enumerate(resto) if _FIN_TABLA.match(l.strip())), len(resto))
    filas, cola = resto[:n_filas], resto[n_filas:]
    if not filas:
        return [texto]
    base = tokenizador.contar([prefijo + "\n".join(cabecera)])[0]
    cuentas = tokenizador.contar(filas)
    partes: list[list[str]] = [[]]
    suma = base
    for fila, n in zip(filas, cuentas):
        if partes[-1] and suma + n > limite:
            partes.append([])
            suma = base
        partes[-1].append(fila)
        suma += n
    textos = ["\n".join(cabecera + grupo) for grupo in partes]
    if cola:
        textos[-1] = "\n".join([textos[-1]] + cola)
    return textos


def fragmentar(segmentos: list[Segmento], doc: TextoDocumento, tokenizador: Tokenizador,
               objetivo: int = 500, maximo: int = 800, solapamiento: int = 80,
               avisos: Avisos | None = None, limite_tabla: int = LIMITE_TABLA) -> list[Fragmento]:
    avisos = avisos or Avisos()
    secciones = MapaSecciones(doc)
    fragmentos: list[Fragmento] = []

    for seg in segmentos:
        base = dict(
            tipo_contenido=seg.tipo_contenido, fuente_texto=seg.fuente_texto, vigente=seg.vigente,
            motivo_exclusion=seg.motivo_exclusion, id_documento_modificatorio=seg.id_documento_modificatorio,
            verificado=seg.verificado, fecha_verificacion=seg.fecha_verificacion,
            transcripcion=seg.transcripcion, modificacion=seg.modificacion,
        )
        prefijo = f"{seg.encabezado}\n" if seg.encabezado else ""
        # Una modificación del documento modificatorio queda en un solo fragmento si cabe en el máximo.
        objetivo_seg = maximo if seg.encabezado else objetivo

        def agregar_tabla(texto: str, seccion: str | None, pagina_inicio: int, pagina_fin: int, datos: dict) -> None:
            partes = partir_tabla(texto, tokenizador, limite_tabla, prefijo)
            if len(partes) > 1:
                avisos.mensajes.append(
                    f"Tabla de más de {limite_tabla} tokens partida en {len(partes)} por grupos de filas: "
                    f"{(seccion or '')[-90:]} (pág. {pagina_inicio})"
                )
            for k, parte in enumerate(partes, 1):
                nombre = f"{seccion} (parte {k} de {len(partes)})" if len(partes) > 1 else seccion
                fragmentos.append(Fragmento(prefijo + parte, nombre, pagina_inicio, pagina_fin, **datos))

        if seg.fuente_texto == "TRANSCRIPCION" and seg.tipo_contenido == "TABLA":
            seccion = seg.seccion or " | ".join(x for x in (secciones.en(seg.inicio), seg.tabla) if x)
            agregar_tabla(seg.texto, seccion, seg.pagina_inicio, seg.pagina_fin, base)
            continue

        # Las transcripciones de texto y los textos sustituidos se dividen solo por frases.
        if not seg.vigente:
            objetivo_seg = maximo
        unidades = _unidades(seg) if seg.fuente_texto != "TRANSCRIPCION" and seg.vigente else [
            _Unidad(t, seg.inicio, nuevo_parrafo=True) for t in _FRASE.split(re.sub(r"\n(?![-•*\d(])", " ", seg.texto))
        ]
        if not unidades:
            continue
        cuentas = tokenizador.contar([u.texto for u in unidades])

        # Frases más largas que el máximo: se parten por palabras (caso raro, se avisa).
        expandidas: list[tuple[_Unidad, int]] = []
        for u, n in zip(unidades, cuentas):
            if n > maximo and not u.es_tabla:
                partes = _partir(u.texto, max(1, len(u.texto.split()) * objetivo // n))
                avisos.mensajes.append(f"Frase de {n} tokens partida en {len(partes)} (pág. {doc.pagina_en(u.inicio)})")
                for parte, m in zip(partes, tokenizador.contar(partes)):
                    expandidas.append((_Unidad(parte, u.inicio, nuevo_parrafo=False), m))
            else:
                expandidas.append((u, n))

        actual: list[tuple[_Unidad, int]] = []
        solo_solape = False

        def emitir(grupo: list[tuple[_Unidad, int]], es_tabla: bool = False) -> None:
            texto = ""
            for u, _ in grupo:
                texto += (("\n" if u.nuevo_parrafo else " ") if texto else "") + u.texto
            inicio = grupo[0][0].inicio
            fin = grupo[-1][0].inicio
            seccion = seg.seccion or secciones.en(inicio)
            if es_tabla and grupo[0][0].titulo_tabla:
                seccion = " | ".join(x for x in (seccion, grupo[0][0].titulo_tabla) if x)
            datos = dict(base)
            if seg.fuente_texto == "TRANSCRIPCION":
                pagina_inicio, pagina_fin = seg.pagina_inicio, seg.pagina_fin
            else:
                pagina_inicio = max(seg.pagina_inicio, doc.pagina_en(inicio))
                pagina_fin = min(seg.pagina_fin, max(doc.pagina_en(fin), doc.pagina_en(inicio)))
            if es_tabla:
                datos["tipo_contenido"] = "TABLA"
                agregar_tabla(texto, seccion, pagina_inicio, pagina_fin, datos)
                return
            fragmentos.append(Fragmento(prefijo + texto, seccion, pagina_inicio, pagina_fin, **datos))

        def cerrar(con_solape: bool) -> None:
            nonlocal actual, solo_solape
            if not actual or solo_solape:
                actual, solo_solape = [], False
                return
            emitir(actual)
            cola: list[tuple[_Unidad, int]] = []
            if con_solape and solapamiento > 0:
                suma = 0
                for u, n in reversed(actual[1:]):
                    if suma + n > solapamiento:
                        break
                    cola.insert(0, (u, n))
                    suma += n
            actual, solo_solape = cola, bool(cola)

        for u, n in expandidas:
            if u.es_tabla:
                cerrar(False)
                if maximo < n <= limite_tabla:
                    avisos.mensajes.append(
                        f"Tabla de {n} tokens (más que el máximo de {maximo}) se mantiene entera: "
                        f"{u.titulo_tabla or ''} (pág. {doc.pagina_en(u.inicio)})"
                    )
                emitir([(u, n)], es_tabla=True)
                actual, solo_solape = [], False
                continue
            total = sum(m for _, m in actual)
            # Apartados y numerales de primer nivel siempre cortan; los niveles más
            # profundos, solo si el fragmento ya tiene la mitad del objetivo.
            if (u.corte_antes and not seg.encabezado and total >= MIN_TOKENS_CORTE
                    and (u.corte_antes <= NIVEL_CORTE or total >= objetivo_seg // 2)):
                cerrar(False)
                total = sum(m for _, m in actual)
            if actual and total + n > maximo:
                cerrar(True)
            actual.append((u, n))
            solo_solape = False
            if sum(m for _, m in actual) >= objetivo_seg:
                cerrar(True)
        cerrar(False)

    textos = [f.texto for f in fragmentos]
    for f, n in zip(fragmentos, tokenizador.contar(textos) if textos else []):
        f.numero_tokens = n
        if (n > maximo and f.tipo_contenido != "TABLA") or n > limite_tabla:
            avisos.mensajes.append(f"Fragmento de {n} tokens (pág. {f.pagina_inicio}): {f.seccion or ''}")
    for i, f in enumerate(fragmentos, 1):
        f.orden = i
        if f.seccion and len(f.seccion) > 200:
            f.seccion = f.seccion[:197] + "..."
    return fragmentos
