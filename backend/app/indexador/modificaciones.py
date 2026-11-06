"""Mapa de las modificaciones que un documento (la RM 429-2024/MINSA) introduce en
otro (la NTS 213 aprobada por la RM 251-2024/MINSA): numeral afectado, tipo,
anclas de inicio y fin del texto sustituido, ancla del texto nuevo y conflictos
derivados."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DIR_MODIFICACIONES = Path(__file__).parent / "modificaciones"
TIPOS = ("modifica", "incorpora", "sustituye")


@dataclass(frozen=True)
class TramoSustituido:
    pagina_inicio: int
    pagina_fin: int
    inicio: str
    fin: str


@dataclass(frozen=True)
class Modificacion:
    numero: int
    numeral: str
    tipo: str
    paginas: tuple[int, int]
    pagina_texto_nuevo: int
    ancla_texto_nuevo: str
    tramos: tuple[TramoSustituido, ...]


@dataclass(frozen=True)
class ConflictoDerivado:
    id: str
    descripcion: str
    modificacion: int
    pagina_inicio: int
    pagina_fin: int
    ancla: str
    excluir: bool


@dataclass(frozen=True)
class MapaModificaciones:
    codigo: str
    documento_modificatorio: str
    id_documento_modificatorio: str
    documento_modificado: str
    modificaciones: tuple[Modificacion, ...]
    conflictos: tuple[ConflictoDerivado, ...] = field(default=())

    def motivo(self, numero: int) -> str:
        return f"Sustituido por {self.codigo}, modificación N.° {numero}"


def _paginas(valor) -> tuple[int, int]:
    if isinstance(valor, int):
        return valor, valor
    return int(valor[0]), int(valor[-1])


def cargar_mapa(nombre: str, base: Path = DIR_MODIFICACIONES) -> MapaModificaciones:
    datos = yaml.safe_load((base / nombre).read_text(encoding="utf-8"))
    modificaciones = []
    for m in datos["modificaciones"]:
        if m["tipo"] not in TIPOS:
            raise ValueError(f"Modificación {m['numero']}: tipo '{m['tipo']}' no válido")
        tramos = tuple(
            TramoSustituido(*_paginas(t["paginas"]), inicio=t["inicio"], fin=t["fin"]) for t in m.get("tramos", [])
        )
        if m["tipo"] != "incorpora" and not tramos:
            raise ValueError(f"Modificación {m['numero']}: falta el texto sustituido (tramos)")
        modificaciones.append(Modificacion(
            numero=int(m["numero"]),
            numeral=str(m["numeral"]),
            tipo=m["tipo"],
            paginas=_paginas(m["paginas"]),
            pagina_texto_nuevo=int(m["texto_nuevo"]["pagina"]),
            ancla_texto_nuevo=m["texto_nuevo"]["ancla"],
            tramos=tramos,
        ))
    conflictos = tuple(
        ConflictoDerivado(
            id=c["id"],
            descripcion=c["descripcion"],
            modificacion=int(c["modificacion"]),
            pagina_inicio=_paginas(c["paginas"])[0],
            pagina_fin=_paginas(c["paginas"])[1],
            ancla=c["ancla"],
            excluir=bool(c.get("excluir", False)),
        )
        for c in datos.get("conflictos_derivados", [])
    )
    numeros = [m.numero for m in modificaciones]
    if numeros != list(range(1, len(numeros) + 1)):
        raise ValueError("Las modificaciones deben numerarse 1, 2, 3... sin saltos")
    return MapaModificaciones(
        codigo=datos["codigo"],
        documento_modificatorio=datos["documento_modificatorio"],
        id_documento_modificatorio=datos["id_documento_modificatorio"],
        documento_modificado=datos["documento_modificado"],
        modificaciones=tuple(modificaciones),
        conflictos=conflictos,
    )
