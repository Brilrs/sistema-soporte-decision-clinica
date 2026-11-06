# Datos de prueba del indexador

`rm251_texto_extraido.txt` y `rm429_texto_extraido.txt` son extractos mínimos del texto que el
indexador obtiene con pdfplumber de la NTS 213 (RM 251-2024/MINSA) y de su modificatoria
(RM 429-2024/MINSA), ya recortado y limpio, con una línea `===== PAGINA n =====` antes de cada
página. Solo conservan, en su página original, las líneas donde caen las anclas de las
modificaciones, de los conflictos derivados y de las transcripciones (más la línea siguiente a
cada ancla de fin, que algunas comprueban), y tres líneas con errores del OCR que las
transcripciones deben reemplazar. Permiten probar en CI las anclas sin los PDF.

Si cambian la extracción, una ancla o una transcripción, se regeneran desde los PDF de
`data/guias` volviendo a seleccionar esas mismas líneas.
