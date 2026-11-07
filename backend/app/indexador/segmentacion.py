"""Une las páginas de un documento en un solo texto, ubica las anclas de las
transcripciones y de las modificaciones, y lo divide en segmentos con su
origen (capa de texto o transcripción) y su vigencia. Los fragmentos nunca
cruzan el borde de un segmento."""
import re
from dataclasses import dataclass, field
from datetime import date

from app.indexador.errores import ErrorAncla, ErrorIndexacion
from app.indexador.extraccion import PaginaTexto
from app.indexador.modificaciones import MapaModificaciones
from app.indexador.transcripciones import Transcripcion

BANDERAS = re.MULTILINE | re.IGNORECASE


@dataclass
class TextoDocumento:
    texto: str
    paginas: list[tuple[int, int, int]]

    @classmethod
    def desde_paginas(cls, paginas: list[PaginaTexto]) -> "TextoDocumento":
        partes, rangos, pos = [], [], 0
        for p in paginas:
            t = p.texto
            rangos.append((p.numero, pos, pos + len(t)))
            partes.append(t)
            pos += len(t) + 1
        return cls("\n".join(partes), rangos)

    def pagina_en(self, posicion: int) -> int:
        for numero, inicio, fin in self.paginas:
            if posicion <= fin:
                return numero
        return self.paginas[-1][0]

    def limites(self, pagina_inicio: int, pagina_fin: int) -> tuple[int, int]:
        rangos = [(i, f) for n, i, f in self.paginas if pagina_inicio <= n <= pagina_fin]
        if not rangos:
            raise ErrorAncla(f"Las páginas {pagina_inicio} a {pagina_fin} no están en el cuerpo extraído")
        return rangos[0][0], rangos[-1][1]

    def buscar_unico(self, patron: str, pagina_inicio: int, pagina_fin: int, descripcion: str,
                     desde: int | None = None) -> re.Match:
        """El ancla debe aparecer exactamente una vez en las páginas indicadas
        (y después de `desde`, si se indica)."""
        inicio, fin = self.limites(pagina_inicio, pagina_fin)
        if desde is not None:
            inicio = max(inicio, desde)
        try:
            expresion = re.compile(patron, BANDERAS)
        except re.error as e:
            raise ErrorAncla(f"{descripcion}: la expresión '{patron}' no es válida ({e})") from e
        hallazgos = list(expresion.finditer(self.texto, inicio, fin))
        if len(hallazgos) != 1:
            paginas = f"pág. {pagina_inicio}" if pagina_inicio == pagina_fin else f"págs. {pagina_inicio} a {pagina_fin}"
            raise ErrorAncla(
                f"{descripcion}: el ancla '{patron}' aparece {len(hallazgos)} veces en {paginas}; debe aparecer una sola vez"
            )
        return hallazgos[0]


@dataclass
class Segmento:
    texto: str
    inicio: int
    fin: int
    pagina_inicio: int
    pagina_fin: int
    tipo_contenido: str = "TEXTO"
    fuente_texto: str = "CAPA_TEXTO"
    vigente: bool = True
    motivo_exclusion: str | None = None
    id_documento_modificatorio: str | None = None
    verificado: bool = False
    fecha_verificacion: date | None = None
    transcripcion: str | None = None
    tabla: str | None = None
    modificacion: int | None = None
    encabezado: str | None = None
    seccion: str | None = None


@dataclass
class _Tramo:
    inicio: int
    fin: int
    etiqueta: str
    transcripcion: Transcripcion | None = None
    motivo: str | None = None


@dataclass
class ResultadoSegmentacion:
    segmentos: list[Segmento]
    anclas: list[dict] = field(default_factory=list)
    conflictos: list[dict] = field(default_factory=list)
    descartado: str = ""


def _tramo_transcripcion(doc: TextoDocumento, t: Transcripcion) -> _Tramo:
    m_ini = doc.buscar_unico(t.ancla_inicio, t.pagina, t.pagina_fin, f"Transcripción {t.clave} (inicio)")
    m_fin = doc.buscar_unico(t.ancla_fin, t.pagina, t.pagina_fin, f"Transcripción {t.clave} (fin)", desde=m_ini.start())
    return _Tramo(m_ini.start(), m_fin.end(), f"transcripción {t.clave}", transcripcion=t)


def _verificar_solapes(tramos: list[_Tramo]) -> None:
    tramos.sort(key=lambda t: t.inicio)
    for a, b in zip(tramos, tramos[1:]):
        if b.inicio < a.fin:
            raise ErrorIndexacion(f"Se superponen {a.etiqueta} y {b.etiqueta}")


def _unir_alrededor_de_conflictos(segmentos: list[Segmento]) -> list[Segmento]:
    """Al excluir una oración (conflicto derivado), el texto vigente de antes y de
    después forma un solo segmento, para no cortar el párrafo en dos fragmentos."""
    resultado: list[Segmento] = []
    i = 0
    while i < len(segmentos):
        s = segmentos[i]
        if (i + 2 < len(segmentos) and s.vigente and s.fuente_texto == "CAPA_TEXTO"
                and (segmentos[i + 1].motivo_exclusion or "").startswith("Conflicto derivado")
                and segmentos[i + 2].vigente and segmentos[i + 2].fuente_texto == "CAPA_TEXTO"
                and segmentos[i + 2].modificacion == s.modificacion):
            siguiente = segmentos[i + 2]
            union = s.texto + ("" if siguiente.texto[:1] in ".,;:" else " ") + siguiente.texto
            resultado.append(Segmento(union, s.inicio, siguiente.fin, s.pagina_inicio, siguiente.pagina_fin,
                                      modificacion=s.modificacion))
            resultado.append(segmentos[i + 1])
            i += 3
            continue
        resultado.append(s)
        i += 1
    return resultado


def _recortar(doc: TextoDocumento, a: int, b: int) -> tuple[str, int, int]:
    """Texto entre a y b sin los espacios y saltos de línea de los extremos, con su
    posición real en el documento. El fragmentador ubica la sección de cada frase
    por su posición: si inicio apuntara a un salto de línea quitado, una frase que
    empieza en un título quedaría con la sección anterior."""
    texto = doc.texto[a:b]
    inicio = a + len(texto) - len(texto.lstrip())
    fin = b - (len(texto) - len(texto.rstrip()))
    return texto.strip(), inicio, max(inicio, fin)


def segmentar(doc: TextoDocumento, transcripciones: list[Transcripcion], mapa: MapaModificaciones | None = None,
              rol: str = "normal") -> ResultadoSegmentacion:
    """rol: 'normal', 'modificado' (la RM 251, con texto sustituido por el mapa)
    o 'modificatorio' (la RM 429, dividida en sus modificaciones)."""
    tramos = [_tramo_transcripcion(doc, t) for t in transcripciones]
    id_modificatorio = mapa.id_documento_modificatorio if mapa and rol == "modificado" else None
    anclas: list[dict] = []
    conflictos: list[dict] = []

    if rol == "modificado" and mapa:
        for m in mapa.modificaciones:
            for k, tr in enumerate(m.tramos, 1):
                nombre = f"Modificación {m.numero} ({m.numeral}), tramo {k}"
                ini = doc.buscar_unico(tr.inicio, tr.pagina_inicio, tr.pagina_fin, f"{nombre}, inicio")
                fin = doc.buscar_unico(tr.fin, tr.pagina_inicio, tr.pagina_fin, f"{nombre}, fin", desde=ini.start())
                tramos.append(_Tramo(ini.start(), fin.end(), nombre.lower(), motivo=mapa.motivo(m.numero)))
                anclas.append({"modificacion": m.numero, "numeral": m.numeral, "tramo": k,
                               "paginas": f"{doc.pagina_en(ini.start())}-{doc.pagina_en(fin.end())}",
                               "caracteres": fin.end() - ini.start()})
        for c in mapa.conflictos:
            try:
                hallazgo = doc.buscar_unico(c.ancla, c.pagina_inicio, c.pagina_fin, f"Conflicto {c.id}")
            except ErrorAncla as e:
                if c.excluir:
                    raise
                conflictos.append({"id": c.id, "descripcion": c.descripcion, "encontrado": False,
                                   "excluido": False, "detalle": str(e)})
                continue
            conflictos.append({"id": c.id, "descripcion": c.descripcion, "encontrado": True, "excluido": c.excluir,
                               "texto": hallazgo.group(0), "pagina": doc.pagina_en(hallazgo.start())})
            if c.excluir:
                tramos.append(_Tramo(hallazgo.start(), hallazgo.end(), f"conflicto {c.id}",
                                     motivo=f"Conflicto derivado con {mapa.codigo}, modificación N.° {c.modificacion}: {c.descripcion}"[:250]))

    _verificar_solapes(tramos)

    cortes: list[tuple[int, int]] = []
    descartado = ""
    if rol == "modificatorio" and mapa:
        for m in mapa.modificaciones:
            hallazgo = doc.buscar_unico(m.ancla_texto_nuevo, m.pagina_texto_nuevo, m.pagina_texto_nuevo,
                                        f"Modificación {m.numero}, texto nuevo")
            cortes.append((hallazgo.start(), m.numero))
            anclas.append({"modificacion": m.numero, "numeral": m.numeral, "tramo": 0,
                           "paginas": str(doc.pagina_en(hallazgo.start())), "caracteres": 0})
        cortes.sort()
        if [n for _, n in cortes] != sorted(n for _, n in cortes):
            raise ErrorIndexacion("Las modificaciones no aparecen en orden en el documento")
        descartado = doc.texto[:cortes[0][0]].strip()
        for t in tramos:
            if any(t.inicio < pos < t.fin for pos, _ in cortes):
                raise ErrorIndexacion(f"La {t.etiqueta} cruza el inicio de una modificación")

    def modificacion_en(pos: int) -> int | None:
        actual = None
        for corte, numero in cortes:
            if pos >= corte:
                actual = numero
        return actual

    segmentos: list[Segmento] = []

    def agregar_texto(inicio: int, fin: int) -> None:
        limites = [inicio] + [c for c, _ in cortes if inicio < c < fin] + [fin]
        for a, b in zip(limites, limites[1:]):
            texto, ini, fin = _recortar(doc, a, b)
            if not texto or (cortes and modificacion_en(a) is None):
                continue
            segmentos.append(Segmento(texto, ini, fin, doc.pagina_en(ini), doc.pagina_en(max(ini, fin - 1)),
                                      modificacion=modificacion_en(a)))

    pos = 0
    for t in tramos:
        agregar_texto(pos, t.inicio)
        if t.transcripcion:
            tr = t.transcripcion
            segmentos.append(Segmento(
                tr.texto, t.inicio, t.fin, tr.pagina, tr.pagina_fin, tipo_contenido=tr.tipo_contenido,
                fuente_texto="TRANSCRIPCION", verificado=tr.verificada, fecha_verificacion=tr.fecha_verificacion,
                transcripcion=tr.clave, tabla=tr.tabla, modificacion=modificacion_en(t.inicio),
            ))
        else:
            texto, ini, fin = _recortar(doc, t.inicio, t.fin)
            segmentos.append(Segmento(
                texto, ini, fin, doc.pagina_en(ini), doc.pagina_en(max(ini, fin - 1)), vigente=False,
                motivo_exclusion=t.motivo, id_documento_modificatorio=id_modificatorio,
            ))
        pos = t.fin
    agregar_texto(pos, len(doc.texto))
    segmentos = _unir_alrededor_de_conflictos(segmentos)

    if rol == "modificatorio" and mapa:
        por_numero = {m.numero: m for m in mapa.modificaciones}
        for s in segmentos:
            m = por_numero[s.modificacion]
            s.encabezado = f"NTS 213 modificada por {mapa.codigo}, numeral {m.numeral}"
            s.seccion = f"{m.numeral} (mod. {mapa.codigo}, modificación N.° {m.numero})"
    return ResultadoSegmentacion(segmentos, anclas, conflictos, descartado)
