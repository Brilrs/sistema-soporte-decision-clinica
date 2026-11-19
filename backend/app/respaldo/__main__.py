"""Línea de comandos del respaldo (imagen de jobs, usuario cdss_indexador). Ver docs/respaldo.md.

    python -m app.respaldo crear [--destino local|blob] [--conservar 7] [--forzar]
    python -m app.respaldo restaurar respaldo_AAAAMMDD_HHMMSS [--coleccion NOMBRE] [--con-guias] [--destino ...]
    python -m app.respaldo verificar [--coleccion NOMBRE]
    python -m app.respaldo comparar guias_clinicas guias_clinicas_prueba_restauracion
    python -m app.respaldo descartar-coleccion guias_clinicas_prueba_restauracion

Código de salida: 0 si todo está bien; 1 si algo falla, no coincide o se niega (con el motivo en la
salida de errores); 2 si los argumentos no son válidos."""
import argparse
import os
import sys
from pathlib import Path

from app.core.vectores import COLECCION, ServidorChroma
from app.indexador.config import DIR_REPOSITORIO
from app.respaldo.destinos import DestinoBlob, DestinoLocal, ErrorRespaldo, cliente_azure_desde_entorno
from app.respaldo.operaciones import (TOLERANCIA_VECTOR, ResultadoVerificacion, comparar, crear, descartar_coleccion,
                                      formato_diferencia, restaurar, verificar)


def _entorno() -> dict:
    return {
        "database_url": os.environ.get("DATABASE_URL_INDEXADOR"),
        "chroma_url": os.environ.get("CHROMA_URL", "http://localhost:8001"),
        "dir_respaldos": Path(os.environ.get("RESPALDO_DIR", DIR_REPOSITORIO / "data" / "respaldos")),
        "dir_guias": Path(os.environ.get("RESPALDO_DIR_GUIAS", DIR_REPOSITORIO / "data" / "guias_cargadas")),
    }


def _fuente(entorno: dict):
    from app.respaldo.postgres import FuentePostgres
    if not entorno["database_url"]:
        raise ErrorRespaldo("Falta DATABASE_URL_INDEXADOR (conexión con el usuario cdss_indexador)")
    return FuentePostgres.desde_url(entorno["database_url"])


def _destino(tipo: str, entorno: dict):
    return DestinoBlob(cliente_azure_desde_entorno()) if tipo == "blob" else DestinoLocal(entorno["dir_respaldos"])


def mostrar_verificacion(v: ResultadoVerificacion) -> None:
    if not v.existe:
        print(f"La colección {v.coleccion} no existe")
        return
    print(f"Colección {v.coleccion}: {v.vectores} vectores, {v.vigentes} vigentes, distancia {v.distancia}")
    print("  por nivel: " + ", ".join(f"nivel {k}: {n}" for k, n in v.por_nivel.items()))
    print("  por estado del documento: " + ", ".join(f"{k}: {n}" for k, n in v.por_estado.items()))
    if v.ok:
        print("  Coincide con PostgreSQL: los ids son los fragmentos de la última versión de cada documento, "
              "con la misma vigencia, estado y nivel.")
    for problema in v.problemas:
        print(f"  NO COINCIDE: {problema}")


def cmd_crear(args, entorno) -> int:
    destino = _destino(args.destino, entorno)
    try:
        r = crear(ServidorChroma(entorno["chroma_url"]), destino, _fuente(entorno), dir_guias=entorno["dir_guias"],
                  coleccion=args.coleccion, forzar=args.forzar, conservar=args.conservar)
    finally:
        getattr(destino, "limpiar", lambda: None)()
    print(f"Respaldo creado: {r.nombre} ({destino.tipo}): {r.vectores} vectores ({r.vigentes} vigentes), "
          f"{r.guias} guías cargadas")
    if r.forzado:
        print("  AVISO: creado con --forzar mientras había trabajos de indexación activos (anotado en el manifiesto)")
    for nombre in r.eliminados:
        print(f"  Respaldo antiguo eliminado (--conservar {args.conservar}): {nombre}")
    return 0


def cmd_restaurar(args, entorno) -> int:
    destino = _destino(args.destino, entorno)
    try:
        r = restaurar(ServidorChroma(entorno["chroma_url"]), destino, _fuente(entorno), args.respaldo,
                      coleccion=args.coleccion, con_guias=args.con_guias, dir_guias=entorno["dir_guias"])
    finally:
        getattr(destino, "limpiar", lambda: None)()
    print(f"Respaldo {r.respaldo} restaurado en la colección {r.coleccion} (misma distancia): {r.vectores} vectores, "
          f"idénticos al respaldo en ids, textos y metadatos; los vectores coinciden con una diferencia máxima de "
          f"{formato_diferencia(r.diferencia_maxima)} por la normalización de ChromaDB "
          f"(tolerancia {TOLERANCIA_VECTOR:g})")
    if args.con_guias:
        print(f"  Guías copiadas: {len(r.guias_copiadas)}; ya estaban iguales: {len(r.guias_existentes)}")
        for archivo in r.guias_distintas:
            print(f"  AVISO: {archivo} ya existe con otro contenido; no se sobrescribió")
    print("Comprobación contra PostgreSQL:")
    mostrar_verificacion(r.verificacion)
    return 0 if r.verificacion.ok else 1


def cmd_verificar(args, entorno) -> int:
    v = verificar(ServidorChroma(entorno["chroma_url"]), _fuente(entorno), args.coleccion)
    mostrar_verificacion(v)
    return 0 if v.ok else 1


def cmd_comparar(args, entorno) -> int:
    r = comparar(ServidorChroma(entorno["chroma_url"]), args.coleccion_a, args.coleccion_b)
    print(f"{args.coleccion_a}: {r.vectores_a} vectores; {args.coleccion_b}: {r.vectores_b} vectores")
    if r.identicas:
        print(f"Las colecciones coinciden: idénticas en ids, textos y metadatos; los vectores coinciden con una "
              f"diferencia máxima de {formato_diferencia(r.diferencia_maxima)} por la normalización de ChromaDB "
              f"(tolerancia {TOLERANCIA_VECTOR:g}), y las {r.consultas} consultas devuelven los mismos 5 primeros "
              "resultados en el mismo orden.")
        return 0
    for diferencia in r.diferencias:
        print(f"  DIFERENCIA: {diferencia}")
    return 1


def cmd_descartar(args, entorno) -> int:
    descartar_coleccion(ServidorChroma(entorno["chroma_url"]), args.nombre)
    print(f"Colección de prueba {args.nombre} descartada")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.respaldo",
                                     description="Respaldo de la colección de ChromaDB y de las guías cargadas")
    sub = parser.add_subparsers(dest="comando", required=True)

    def destino(p):
        p.add_argument("--destino", choices=["local", "blob"], default="local",
                       help="carpeta local (RESPALDO_DIR) o Azure Blob (RESPALDO_CONTENEDOR_BLOB)")

    p = sub.add_parser("crear", help="exporta la colección y las guías cargadas a una carpeta con fecha")
    destino(p)
    p.add_argument("--conservar", type=int, default=7, help="respaldos que se conservan en este destino (7)")
    p.add_argument("--forzar", action="store_true", help="respaldar aunque haya trabajos de indexación activos")
    p.add_argument("--coleccion", default=COLECCION, help=argparse.SUPPRESS)
    p.set_defaults(funcion=cmd_crear)

    p = sub.add_parser("restaurar", help="restaura un respaldo en una colección vacía o nueva")
    p.add_argument("respaldo", help="nombre del respaldo (respaldo_AAAAMMDD_HHMMSS) o carpeta")
    destino(p)
    p.add_argument("--coleccion", default=COLECCION, help="colección destino (por omisión guias_clinicas)")
    p.add_argument("--con-guias", action="store_true", help="copia también los PDF que faltan en el volumen")
    p.set_defaults(funcion=cmd_restaurar)

    p = sub.add_parser("verificar", help="comprueba una colección contra PostgreSQL (solo lectura)")
    p.add_argument("--coleccion", default=COLECCION)
    p.set_defaults(funcion=cmd_verificar)

    p = sub.add_parser("comparar", help="comprueba que dos colecciones coinciden (vectores con tolerancia 1e-6)")
    p.add_argument("coleccion_a")
    p.add_argument("coleccion_b")
    p.set_defaults(funcion=cmd_comparar)

    p = sub.add_parser("descartar-coleccion", help="borra una colección de prueba (guias_clinicas_prueba_...)")
    p.add_argument("nombre")
    p.set_defaults(funcion=cmd_descartar)

    args = parser.parse_args(argv)
    try:
        return args.funcion(args, _entorno())
    except ErrorRespaldo as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 (programado: cualquier fallo da código 1 con un motivo)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
