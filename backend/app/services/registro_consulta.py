"""Registro de la consulta con la sesión de cdss_clinica (nodo validar del grafo).

Es el único lugar del flujo de la consulta que escribe asistencia.consulta.texto_consulta:
el texto original queda en el servidor y solo lo puede leer cdss_clinica. Los módulos de
app/rag no tienen SQL con esa columna (lo comprueba test_rag_unidad)."""
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session


def registrar_consulta(sesion: Session | Connection, id_tamizaje: str, id_usuario: str, texto_consulta: str,
                       texto_filtrado: str, idioma_respuesta: str, confirma_tamizaje_no_vigente: bool,
                       id_consulta_previa: str | None = None) -> str:
    return sesion.execute(text(
        """INSERT INTO asistencia.consulta (id_consulta_previa, id_tamizaje, id_usuario, texto_consulta,
                                            texto_filtrado, idioma_respuesta, confirma_tamizaje_no_vigente)
           VALUES (CAST(:p AS uuid), CAST(:t AS uuid), CAST(:u AS uuid), :tc, :tf, :i, :conf)
           RETURNING id_consulta::text"""),
        {"p": id_consulta_previa, "t": id_tamizaje, "u": id_usuario, "tc": texto_consulta, "tf": texto_filtrado,
         "i": idioma_respuesta, "conf": confirma_tamizaje_no_vigente}).scalar_one()


def registrar_datos_faltantes(sesion: Session | Connection, id_consulta: str, faltantes) -> None:
    for f in faltantes:
        sesion.execute(text("INSERT INTO asistencia.dato_faltante (id_consulta, campo, mensaje) "
                            "VALUES (CAST(:c AS uuid), :campo, :m)"), {"c": id_consulta, "campo": f.campo,
                                                                       "m": f.mensaje})
