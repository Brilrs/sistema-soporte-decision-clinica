"""PDF del reporte exportable con ReportLab, en memoria (Sprint 3, parte C1).

- Fuente DejaVu Sans empaquetada en fuentes/ (licencia en fuentes/LICENSE_DEJAVU.txt): cubre las
  tildes, la ñ, ¿ ¡, ≥ ≤, N° y «», que las fuentes base de PDF no tienen. ReportLab incrusta solo
  los caracteres usados, con su tabla para copiar y buscar el texto.
- invariant=1: sin fecha de creación ni identificador aleatorio en el archivo; el mismo contenido
  da los mismos bytes.
- Cada página repite el número del reporte y los avisos (modo de prueba y texto en revisión), así
  una hoja suelta no se confunde con un documento clínico válido.
- Los metadatos del PDF (título, asunto) llevan solo el número: nunca datos del paciente.
- Nada se escribe en disco: el documento se arma en un BytesIO y se devuelven sus bytes."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reportes.contenido import fecha_hora

FUENTES = Path(__file__).with_name("fuentes")
NORMAL, NEGRITA = "DejaVuSans", "DejaVuSans-Bold"
AZUL = colors.HexColor("#1b2f6b")
GRIS = colors.HexColor("#4b5563")
ROJO = colors.HexColor("#b42318")
MARGEN = 18 * mm
ALTO_CABECERA = 16 * mm


def registrar_fuentes() -> None:
    if NORMAL not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(NORMAL, str(FUENTES / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(NEGRITA, str(FUENTES / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily(NORMAL, normal=NORMAL, bold=NEGRITA, italic=NORMAL, boldItalic=NEGRITA)


def _estilos() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName=NORMAL, fontSize=9.5, leading=13, textColor=colors.black)
    return {
        "base": base,
        "titulo": ParagraphStyle("titulo", parent=base, fontName=NEGRITA, fontSize=15, leading=19, textColor=AZUL),
        "subtitulo": ParagraphStyle("subtitulo", parent=base, textColor=GRIS),
        "seccion": ParagraphStyle("seccion", parent=base, fontName=NEGRITA, fontSize=11.5, leading=15, textColor=AZUL,
                                  spaceBefore=8, spaceAfter=3),
        "etiqueta": ParagraphStyle("etiqueta", parent=base, fontName=NEGRITA),
        "detalle": ParagraphStyle("detalle", parent=base, fontSize=8.5, leading=11.5, textColor=GRIS, leftIndent=10),
        "item": ParagraphStyle("item", parent=base, leftIndent=10, spaceBefore=2),
        "final": ParagraphStyle("final", parent=base, fontName=NEGRITA, spaceBefore=10),
        "pie": ParagraphStyle("pie", parent=base, fontSize=8, leading=10, textColor=GRIS),
        "firma": ParagraphStyle("firma", parent=base, alignment=TA_CENTER, textColor=GRIS),
    }


def _p(texto: str, estilo: ParagraphStyle) -> Paragraph:
    # Paragraph interpreta un XML sencillo: el texto de la consulta se escapa siempre.
    return Paragraph(escape(texto).replace("\n", "<br/>"), estilo)


def _bloque(b: dict, e: dict) -> list:
    partes: list = [_p(b["titulo"], e["seccion"])]
    if b["campos"]:
        filas = [[_p(c["etiqueta"], e["etiqueta"]), _p(c["valor"], e["base"])] for c in b["campos"]]
        tabla = Table(filas, colWidths=[48 * mm, None], hAlign="LEFT")
        tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
        partes.append(tabla)
    partes += [_p(t, e["base"]) for t in b["parrafos"]]
    for item in b["items"]:
        partes.append(_p(("• " if not item["texto"][:1].isdigit() else "") + item["texto"], e["item"]))
        partes += [_p(t, e["detalle"]) for t in item["detalle"]]
    return [KeepTogether(partes[:2]), *partes[2:]]


def generar_pdf(contenido: dict, numero: str, fecha_emision: datetime) -> bytes:
    """Bytes del PDF del reporte. No toca el disco."""
    registrar_fuentes()
    e = _estilos()
    avisos = contenido["avisos"]
    alto_avisos = 6 * mm * len(avisos)

    def decorar(lienzo, doc):
        lienzo.saveState()
        ancho, alto = A4
        y = alto - 10 * mm
        lienzo.setFont(NEGRITA, 8.5)
        lienzo.setFillColor(AZUL)
        lienzo.drawString(MARGEN, y, contenido["establecimiento"])
        lienzo.drawRightString(ancho - MARGEN, y, f"N.° {numero}")
        for aviso in avisos:
            y -= 6 * mm
            lienzo.setFillColor(ROJO)
            lienzo.setFont(NEGRITA, 9)
            lienzo.drawCentredString(ancho / 2, y, aviso)
        lienzo.setFont(NORMAL, 7.5)
        lienzo.setFillColor(GRIS)
        lienzo.drawString(MARGEN, 10 * mm, f"{numero} · Emitido el {fecha_hora(fecha_emision)}")
        lienzo.drawRightString(ancho - MARGEN, 10 * mm, f"Página {doc.page}")
        lienzo.restoreState()

    salida = BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=A4, leftMargin=MARGEN, rightMargin=MARGEN,
                            topMargin=ALTO_CABECERA + alto_avisos + 4 * mm, bottomMargin=18 * mm,
                            title=f"Reporte {numero}", subject="Reporte de evaluación de anemia infantil",
                            author="CDSS Anemia Infantil", creator="CDSS Anemia Infantil", invariant=1)
    historia: list = [
        _p(contenido["titulo"], e["titulo"]),
        _p(f"{contenido['establecimiento']} · Reporte N.° {numero} · Emitido el {fecha_hora(fecha_emision)}",
           e["subtitulo"]),
        Spacer(1, 3 * mm),
    ]
    if contenido.get("introduccion"):
        historia += [_p(contenido["introduccion"], e["base"]), Spacer(1, 2 * mm)]
    for b in contenido["bloques"]:
        historia += _bloque(b, e)
    historia.append(_p(contenido["frase_final"], e["final"]))
    historia.append(_p(f"Generado por: {contenido['generado_por']} · {fecha_hora(fecha_emision)}", e["pie"]))
    if contenido["firma"]:
        linea = Table([[""]], colWidths=[70 * mm], rowHeights=[16 * mm], hAlign="RIGHT")
        linea.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.black)]))
        firma = Table([[_p("Firma y sello del profesional", e["firma"])]], colWidths=[70 * mm], hAlign="RIGHT")
        historia += [Spacer(1, 6 * mm), KeepTogether([linea, firma])]
    doc.build(historia, onFirstPage=decorar, onLaterPages=decorar)
    return salida.getvalue()
