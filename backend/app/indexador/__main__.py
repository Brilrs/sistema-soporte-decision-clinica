"""Línea de comandos del indexador (contenedor jobs):

    python -m app.indexador cargar --manifiesto fuentes_iniciales.yaml
    python -m app.indexador procesar --documento rm251 [--reindexar]
    python -m app.indexador comparar
    python -m app.indexador verificar-valores
    python -m app.indexador trabajador
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from app.indexador.config import ConfigIndexador, FuenteDocumento, cargar_config, cargar_manifiesto
from app.indexador.extraccion import extraer_pdf
from app.indexador.indexacion import Indexador, Opciones, Resultado, preparar
from app.indexador.informes import informe_extraccion, informe_valores, seccion_documento
from app.indexador.pagina_verificacion import pagina_verificacion

MANIFIESTO = "fuentes_iniciales.yaml"
log = logging.getLogger("indexador")


def _servicios(config: ConfigIndexador, falsos: bool):
    from app.indexador.servicios import (ClienteModelos, EmbedderFalso, EmbedderHttp, TokenizadorFalso,
                                         TokenizadorHttp)
    if falsos:
        return EmbedderFalso(), TokenizadorFalso()
    cliente = ClienteModelos(config.modelos_url)
    return EmbedderHttp(cliente), TokenizadorHttp(cliente)


def _indexador(config: ConfigIndexador, falsos: bool) -> Indexador:
    from app.indexador.repositorio import Repositorio
    from app.indexador.vectores import AlmacenChroma
    if not config.database_url:
        sys.exit("Falta DATABASE_URL_INDEXADOR (conexión con el usuario cdss_indexador)")
    embedder, tokenizador = _servicios(config, falsos)
    return Indexador(Repositorio.desde_url(config.database_url), AlmacenChroma(config.chroma_url), embedder,
                     tokenizador, config.lote_progreso)


def _ruta_pdf(config: ConfigIndexador, fuente: FuenteDocumento, ruta_blob: str | None = None) -> Path:
    if ruta_blob and ruta_blob.startswith("local://"):
        carpeta, _, nombre = ruta_blob.removeprefix("local://").partition("/")
        base = config.dir_guias if carpeta == "guias" else config.dir_guias.parent / carpeta
        return base / nombre
    return config.dir_guias / fuente.archivo


def _mostrar(fuente: FuenteDocumento, r: Resultado) -> None:
    linea = f"{fuente.clave}: {r.estado}"
    if r.estado == "COMPLETADA":
        ritmo = r.total / r.segundos_embeddings if r.segundos_embeddings else 0
        linea += (f", versión {r.version}, {r.total} fragmentos ({r.vigentes} vigentes, {r.no_verificadas} de "
                  f"transcripciones sin verificar), {r.segundos_total:.1f} s en total, embeddings a "
                  f"{ritmo:.2f} fragmentos/s")
    elif r.mensaje:
        linea += f": {r.mensaje}"
    print(linea, flush=True)
    for aviso in r.avisos:
        print(f"  aviso: {aviso}")


def _indexar_fuente(indexador: Indexador, config: ConfigIndexador, fuente: FuenteDocumento, opciones: Opciones,
                    ruta: Path | None = None) -> Resultado:
    tipo = "REINDEXACION" if indexador.repo.version_actual(fuente.id_documento) else "INDEXACION"
    id_trabajo = indexador.repo.crear_trabajo(fuente.id_documento, tipo, estado="EN_CURSO")
    resultado = indexador.indexar(fuente, ruta or _ruta_pdf(config, fuente), opciones, id_trabajo)
    _mostrar(fuente, resultado)
    return resultado


def cmd_cargar(args, config: ConfigIndexador) -> int:
    fuentes = cargar_manifiesto(args.manifiesto)
    if args.solo:
        fuentes = [f for f in fuentes if f.clave in args.solo]
    faltantes = [f.archivo for f in fuentes if not (config.dir_guias / f.archivo).is_file()]
    if faltantes:
        print(f"Faltan en {config.dir_guias}: {', '.join(faltantes)}", file=sys.stderr)
        return 1
    indexador = _indexador(config, args.falsos)
    opciones = Opciones(args.permitir_no_verificadas, args.reindexar)
    resultados = [_indexar_fuente(indexador, config, f, opciones) for f in fuentes]
    return 0 if all(r.estado != "ERROR" for r in resultados) else 2


def _fuente(clave_o_id: str, manifiesto: str) -> FuenteDocumento:
    for f in cargar_manifiesto(manifiesto):
        if clave_o_id in (f.clave, f.id_documento):
            return f
    return FuenteDocumento(clave=clave_o_id, id_documento=clave_o_id, archivo="")


def cmd_procesar(args, config: ConfigIndexador) -> int:
    fuente = _fuente(args.documento, args.manifiesto)
    indexador = _indexador(config, args.falsos)
    ruta = Path(args.archivo) if args.archivo else None
    if ruta is None and not fuente.archivo:
        ruta = _ruta_pdf(config, fuente, indexador.repo.documento(fuente.id_documento).ruta_blob)
    r = _indexar_fuente(indexador, config, fuente, Opciones(args.permitir_no_verificadas, args.reindexar), ruta)
    return 0 if r.estado != "ERROR" else 2


def cmd_comparar(args, config: ConfigIndexador) -> int:
    from app.indexador.repositorio import Repositorio
    _, tokenizador = _servicios(config, args.falsos)
    repo = Repositorio.desde_url(config.database_url) if config.database_url else None
    almacen = None
    if repo and not args.sin_chroma:
        from app.indexador.vectores import AlmacenChroma
        almacen = AlmacenChroma(config.chroma_url)
    secciones = []
    for fuente in cargar_manifiesto(args.manifiesto):
        ruta = config.dir_guias / fuente.archivo
        if not ruta.is_file():
            secciones.append([f"## {fuente.clave}", "", f"No se encontró {fuente.archivo} en {config.dir_guias}.", ""])
            continue
        documento = repo.documento(fuente.id_documento) if repo else None
        inicio, fin, titulo = (documento.pagina_inicio_cuerpo, documento.pagina_fin_cuerpo, documento.titulo) \
            if documento else (None, None, fuente.clave)
        parametros = repo.parametros_fragmentacion() if repo else (500, 800, 80)
        prep = preparar(fuente, extraer_pdf(ruta, inicio, fin, fuente.recorte), tokenizador, parametros)
        conteo = None
        if repo and almacen and documento and documento.estado_indexacion == "COMPLETADA":
            version = repo.version_actual(fuente.id_documento)
            conteo = (repo.contar_fragmentos(fuente.id_documento, version),
                      len(almacen.ids_de_documento(fuente.id_documento)))
        secciones.append(seccion_documento(fuente, titulo, prep, parametros[1], conteo))
        print(f"{fuente.clave}: {len(prep.fragmentos)} fragmentos", flush=True)
    salida = Path(args.salida) if args.salida else config.dir_mediciones / "a2_extraccion.md"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(informe_extraccion(secciones, "falso" if args.falsos else "bge-m3"), encoding="utf-8")
    print(f"Informe: {salida}")
    return 0


def cmd_verificar_valores(args, config: ConfigIndexador) -> int:
    salida = Path(args.salida) if args.salida else config.dir_mediciones / "verificacion_valores_criticos.md"
    salida.parent.mkdir(parents=True, exist_ok=True)
    fuentes = cargar_manifiesto(args.manifiesto)
    salida.write_text(informe_valores(fuentes), encoding="utf-8")
    print(f"Lista de comprobación: {salida}")
    pagina = salida.parent / "verificacion.html"
    pagina.write_text(pagina_verificacion(fuentes, salida.parent), encoding="utf-8")
    print(f"Página de verificación: {pagina}")
    return 0


def cmd_trabajador(args, config: ConfigIndexador) -> int:
    indexador = _indexador(config, args.falsos)
    print(f"Trabajador en espera de trabajos PENDIENTE (cada {config.intervalo_trabajador_s:.0f} s)", flush=True)
    while True:
        trabajo = indexador.repo.tomar_trabajo()
        if trabajo is None:
            if args.una_vez:
                return 0
            time.sleep(config.intervalo_trabajador_s)
            continue
        fuente = _fuente(trabajo.id_documento, args.manifiesto)
        if trabajo.tipo == "RETIRO":
            indexador.repo.finalizar_trabajo(trabajo.id_trabajo, "El retiro de guías (HU17) se implementa en el Sprint 3")
            continue
        documento = indexador.repo.documento(trabajo.id_documento)
        ruta = _ruta_pdf(config, fuente, documento.ruta_blob if not fuente.archivo else None)
        opciones = Opciones(args.permitir_no_verificadas, reindexar=trabajo.tipo == "REINDEXACION")
        _mostrar(fuente, indexador.indexar(fuente, ruta, opciones, trabajo.id_trabajo))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.indexador", description="Indexador de guías clínicas")
    sub = parser.add_subparsers(dest="comando", required=True)

    def comunes(p, indexa: bool = True):
        p.add_argument("--manifiesto", default=MANIFIESTO, help="manifiesto de fuentes (por defecto %(default)s)")
        p.add_argument("--falsos", action="store_true", help="embeddings y tokens falsos, sin el servicio modelos")
        if indexa:
            p.add_argument("--permitir-no-verificadas", action="store_true",
                           help="solo desarrollo: indexa transcripciones sin verificar, marcadas como no verificadas")

    p = sub.add_parser("cargar", help="calcula el SHA-256 de los PDF del manifiesto y los indexa")
    comunes(p)
    p.add_argument("--reindexar", action="store_true", help="crea una versión nueva aunque el archivo no cambió")
    p.add_argument("--solo", nargs="+", metavar="CLAVE", help="solo estas claves del manifiesto")
    p.set_defaults(func=cmd_cargar)

    p = sub.add_parser("procesar", help="indexa un documento (clave del manifiesto o id)")
    comunes(p)
    p.add_argument("--documento", required=True)
    p.add_argument("--archivo", help="ruta del PDF, si no es la del manifiesto")
    p.add_argument("--reindexar", action="store_true")
    p.set_defaults(func=cmd_procesar)

    p = sub.add_parser("comparar", help="informe de extracción en a2_extraccion.md (no escribe en la base)")
    comunes(p, indexa=False)
    p.add_argument("--salida")
    p.add_argument("--sin-chroma", action="store_true", help="no consulta ChromaDB para comparar conteos")
    p.set_defaults(func=cmd_comparar)

    p = sub.add_parser("verificar-valores", help="lista de comprobación de los valores críticos")
    comunes(p, indexa=False)
    p.add_argument("--salida")
    p.set_defaults(func=cmd_verificar_valores)

    p = sub.add_parser("trabajador", help="toma trabajos PENDIENTE de conocimiento.trabajo_indexacion")
    comunes(p)
    p.add_argument("--una-vez", action="store_true", help="termina cuando no quedan trabajos pendientes")
    p.set_defaults(func=cmd_trabajador)

    args = parser.parse_args(argv)
    return args.func(args, cargar_config())


if __name__ == "__main__":
    sys.exit(main())
