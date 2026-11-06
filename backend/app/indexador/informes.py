"""Informes para revisión humana: lista de comprobación de los valores críticos
(verificar-valores) e informe de extracción por documento (comparar)."""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from app.indexador.config import DIR_PAQUETE, FuenteDocumento
from app.indexador.extraccion import detectar_sospechosos
from app.indexador.indexacion import Preparacion
from app.indexador.transcripciones import DIR_TRANSCRIPCIONES, leer_transcripcion

RUTA_VALORES = DIR_PAQUETE / "valores_criticos.yaml"
BANDERAS = re.DOTALL


@dataclass(frozen=True)
class ValorCritico:
    id: str
    descripcion: str
    transcripcion: str
    regex: str


def cargar_valores(ruta: Path = RUTA_VALORES) -> list[ValorCritico]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return [ValorCritico(**v) for v in datos["valores"]]


def buscar_valor(valor: ValorCritico, texto: str) -> re.Match | None:
    return re.search(valor.regex, texto, BANDERAS)


def ruta_imagen(prefijo: str | None, pagina: int) -> str:
    return f"data/mediciones/paginas/{prefijo or 'documento'}-{pagina:02d}.png"


def informe_valores(fuentes: list[FuenteDocumento], valores: list[ValorCritico] | None = None) -> str:
    valores = valores or cargar_valores()
    prefijos = {f.transcripciones: f.prefijo_imagen for f in fuentes if f.transcripciones}
    lineas = [
        "# Verificación de valores críticos",
        "",
        f"Generado el {date.today():%d/%m/%Y} con `python -m app.indexador verificar-valores`.",
        "",
        "Para cada valor: abra la imagen de la página, compare el texto transcrito y marque la casilla.",
        "Cuando todos los valores de una transcripción estén conformes, complete en su encabezado",
        "`verificado_por` y `fecha_verificacion` (AAAA-MM-DD) y vuelva a indexar el documento con",
        "`procesar --reindexar`. Las imágenes se generan con el contenedor temporal de Poppler (jobs/README.md).",
        "",
    ]
    actual = None
    for v in valores:
        t = leer_transcripcion(DIR_TRANSCRIPCIONES / f"{v.transcripcion}.md")
        if t.documento != actual:
            actual = t.documento
            lineas += [f"## {actual}", ""]
        hallazgo = buscar_valor(v, t.texto)
        paginas = str(t.pagina) if t.pagina == t.pagina_fin else f"{t.pagina} y {t.pagina_fin}"
        imagenes = ", ".join(f"`{ruta_imagen(prefijos.get(v.transcripcion.split('/')[0]), p)}`"
                             for p in range(t.pagina, t.pagina_fin + 1))
        texto = re.sub(r"\s+", " ", hallazgo.group(0)) if hallazgo else "NO ENCONTRADO en la transcripción"
        estado = "verificada" if t.verificada else "sin verificar"
        lineas += [
            f"- [ ] **{v.id}**: {v.descripcion}",
            f"  - Página {paginas}: {imagenes}",
            f"  - Transcripción: `backend/app/indexador/transcripciones/{v.transcripcion}.md` ({estado})",
            f"  - Texto transcrito: «{texto}»",
        ]
    return "\n".join(lineas) + "\n"


def _tabla(filas: list[list], encabezado: list[str]) -> list[str]:
    salida = ["| " + " | ".join(encabezado) + " |", "| " + " | ".join("---" for _ in encabezado) + " |"]
    salida += ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in f) + " |" for f in filas]
    return salida


def seccion_documento(fuente: FuenteDocumento, titulo: str, prep: Preparacion, maximo: int,
                      conteo_bd: tuple[int, int] | None = None) -> list[str]:
    fr = prep.fragmentos
    tokens = [f.numero_tokens for f in fr]
    no_vigentes = [f for f in fr if not f.vigente]
    lineas = [
        f"## {titulo} (`{fuente.clave}`)",
        "",
        f"- Páginas procesadas: {prep.paginas[0].numero} a {prep.paginas[-1].numero} ({len(prep.paginas)})",
        f"- Fragmentos: {len(fr)} ({len(fr) - len(no_vigentes)} vigentes, {len(no_vigentes)} no vigentes)",
        f"- Tamaño en tokens: mínimo {min(tokens)}, promedio {sum(tokens) // len(tokens)}, máximo {max(tokens)}; "
        f"{sum(t > maximo for t in tokens)} sobre el máximo de {maximo}",
        f"- Tablas: {sum(f.tipo_contenido == 'TABLA' for f in fr)} fragmentos de tabla",
        f"- Transcripciones: {len(prep.transcripciones)} "
        f"({sum(not t.verificada for t in prep.transcripciones)} sin verificar)",
    ]
    if conteo_bd is not None:
        pg, chroma = conteo_bd
        estado = "coinciden" if pg == chroma else "NO coinciden"
        lineas.append(f"- Versión indexada: {pg} fragmentos en PostgreSQL y {chroma} vectores en ChromaDB ({estado})")
    if prep.segmentacion.descartado:
        descartado = re.sub(r"\s+", " ", prep.segmentacion.descartado)[:160]
        lineas.append(f"- Texto descartado antes de la primera modificación: «{descartado}»")

    sospechosos = [(n, c) for n, c in prep.sospechosos_por_pagina.items() if c]
    lineas += ["", "### Tokens sospechosos del OCR", ""]
    if sospechosos:
        filas = []
        for n, c in sospechosos:
            pagina = next(p for p in prep.paginas if p.numero == n)
            ejemplos = [x for v in detectar_sospechosos(pagina.texto).values() for x in v][:6]
            cubierta = [t.clave for t in prep.transcripciones if t.pagina <= n <= t.pagina_fin]
            reemplazo = "transcripción: " + ", ".join(cubierta) if cubierta else "revisar"
            filas.append([n, c, " ; ".join(ejemplos), reemplazo])
        lineas += _tabla(filas, ["Página", "Cantidad", "Ejemplos", "Tratamiento"])
    else:
        lineas.append("Ninguno.")

    if prep.transcripciones:
        lineas += ["", "### Tablas y párrafos transcritos a mano", ""]
        lineas += _tabla(
            [[t.clave, t.pagina if t.pagina == t.pagina_fin else f"{t.pagina}-{t.pagina_fin}", t.tabla,
              "sí" if t.verificada else "no"] for t in prep.transcripciones],
            ["Transcripción", "Página", "Contenido", "Verificada"],
        )
    if prep.segmentacion.anclas:
        lineas += ["", "### Anclas de las modificaciones", ""]
        lineas += _tabla([[a["modificacion"], a["numeral"], a["tramo"] or "texto nuevo", a["paginas"],
                           a["caracteres"] or ""] for a in prep.segmentacion.anclas],
                         ["Modificación", "Numeral", "Tramo", "Páginas", "Caracteres sustituidos"])
    if no_vigentes:
        lineas += ["", "### Fragmentos no vigentes", ""]
        lineas += _tabla([[f.orden, f"{f.pagina_inicio}-{f.pagina_fin}", f.motivo_exclusion,
                           re.sub(r"\s+", " ", f.texto)[:90]] for f in no_vigentes],
                         ["Orden", "Páginas", "Motivo", "Inicio del texto"])
    if prep.segmentacion.conflictos:
        lineas += ["", "### Conflictos derivados", ""]
        lineas += _tabla([[c["id"], c.get("pagina", ""), "excluido" if c["excluido"] else "solo informado",
                           "sí" if c["encontrado"] else "no", c["descripcion"]] for c in prep.segmentacion.conflictos],
                         ["Conflicto", "Página", "Tratamiento", "Encontrado", "Descripción"])
    if prep.avisos:
        lineas += ["", "### Avisos de la fragmentación", ""] + [f"- {a}" for a in prep.avisos]
    return lineas + [""]


def informe_extraccion(secciones: list[list[str]], tokenizador: str) -> str:
    cabecera = [
        "# Informe de extracción (Sprint 2, A2)",
        "",
        f"Generado el {date.today():%d/%m/%Y} con `python -m app.indexador comparar` "
        f"(tokenizador {tokenizador}). No escribe en la base de datos.",
        "",
    ]
    return "\n".join(cabecera + [l for s in secciones for l in s])
