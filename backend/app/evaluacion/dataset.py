"""Carga y validación del conjunto de casos (docs/diseno_evaluacion_oe3.md, sección 5).

Cada caso es un YAML validado contra esquema_caso.json con un validador propio del subconjunto de
JSON Schema que usa el esquema (tipos, enum, required, additionalProperties, pattern, minLength,
minItems, maxItems, uniqueItems, minimum y format date): así no se agrega jsonschema al sistema.
La huella del conjunto es el SHA-256 de las líneas «archivo, dos espacios, SHA-256 del archivo»,
ordenadas por nombre."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ESQUEMA = "esquema_caso.json"
GRUPOS = ("piloto", "evaluacion")
DIR_CONJUNTO_DEFECTO = Path(os.environ.get("EVALUACION_DIR_CONJUNTO", "/datos/conjunto"))
# DNI ficticios de seed_demo (app/scripts/seed_demo.py); los ficticios del conjunto empiezan con 89.
PREFIJO_FICTICIO = "89"

_TIPOS = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
          "boolean": bool, "null": type(None)}


class ErrorConjunto(Exception):
    """El conjunto no se puede usar (casos inválidos, ids repetidos o carpeta vacía)."""


@dataclass(frozen=True)
class Alternativa:
    documento: str
    paginas: tuple[int, int]
    numeral: str
    texto_anclaje: str
    equivalencia_pendiente: bool = False


@dataclass(frozen=True)
class Criterio:
    id: str
    descripcion: str
    obligatorio: bool
    alternativas: tuple[Alternativa, ...]


@dataclass
class Caso:
    id: str
    archivo: str
    sha256: str
    datos: dict

    @property
    def criterios(self) -> list[Criterio]:
        return [Criterio(c["id"], c["descripcion"], c["obligatorio"],
                         tuple(Alternativa(a["documento"], tuple(a["paginas"]), a["numeral"], a["texto_anclaje"],
                                           bool(a.get("equivalencia_pendiente", False)))
                               for a in c["alternativas"]))
                for c in self.datos["criterios"]]

    def __getitem__(self, clave):
        return self.datos[clave]


@dataclass
class Conjunto:
    grupo: str
    casos: list[Caso]
    huella: str
    huella_esquema: str
    huellas: dict[str, str] = field(default_factory=dict)

    def manifiesto(self) -> dict:
        return {"grupo": self.grupo, "casos": len(self.casos), "huella_conjunto_sha256": self.huella,
                "huella_esquema_sha256": self.huella_esquema, "archivos": self.huellas}


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def huella_conjunto(huellas: dict[str, str]) -> str:
    lineas = "".join(f"{nombre}  {h}\n" for nombre, h in sorted(huellas.items()))
    return sha256(lineas.encode("utf-8"))


def _a_json(v):
    """YAML lee las fechas como date: el esquema las pide como texto ISO."""
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _a_json(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_a_json(x) for x in v]
    return v


def validar_esquema(v, s: dict, ruta: str = "$") -> list[str]:
    """Errores de `v` frente al esquema `s` (subconjunto de JSON Schema descrito arriba)."""
    errores: list[str] = []
    t = s.get("type")
    if t:
        tipos = t if isinstance(t, list) else [t]
        ok = any(isinstance(v, _TIPOS[x]) and not (x in ("integer", "number") and isinstance(v, bool)) for x in tipos)
        if not ok:
            return [f"{ruta}: se esperaba {t}, llegó {type(v).__name__}"]
    if "enum" in s and v not in s["enum"]:
        errores.append(f"{ruta}: {v!r} no es un valor permitido")
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            errores.append(f"{ruta}: no cumple el patrón {s['pattern']}")
        if len(v) < s.get("minLength", 0):
            errores.append(f"{ruta}: demasiado corto")
        if s.get("format") == "date":
            try:
                dt.date.fromisoformat(v)
            except ValueError:
                errores.append(f"{ruta}: fecha inválida")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "minimum" in s and v < s["minimum"]:
        errores.append(f"{ruta}: menor que {s['minimum']}")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0) or len(v) > s.get("maxItems", len(v)):
            errores.append(f"{ruta}: cantidad de elementos fuera de rango")
        if s.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in v}) != len(v):
            errores.append(f"{ruta}: elementos repetidos")
        for i, x in enumerate(v):
            errores += validar_esquema(x, s.get("items", {}), f"{ruta}[{i}]")
    if isinstance(v, dict):
        props = s.get("properties", {})
        errores += [f"{ruta}: falta {k}" for k in s.get("required", []) if k not in v]
        if s.get("additionalProperties") is False:
            errores += [f"{ruta}: campo no permitido {k}" for k in v if k not in props]
        for k, x in v.items():
            if k in props:
                errores += validar_esquema(x, props[k], f"{ruta}.{k}")
    return errores


def _dnis_seed() -> frozenset[str]:
    from app.scripts.seed_demo import PACIENTES
    return frozenset(p[1] for p in PACIENTES)


def validar_caso(datos: dict, esquema: dict, grupo: str | None = None) -> list[str]:
    """Esquema más las reglas que el esquema no expresa."""
    datos = _a_json(datos)
    errores = validar_esquema(datos, esquema)
    if errores:
        return errores
    if grupo and datos["conjunto"] != grupo:
        errores.append(f"conjunto {datos['conjunto']!r} en la carpeta {grupo!r}")
    if [c["id"] for c in datos["criterios"]] != [f"C{i + 1}" for i in range(len(datos["criterios"]))]:
        errores.append("los criterios deben ser C1, C2, ... en orden")
    if datos["estado_esperado"] == "VERIFICADA" and not any(c["obligatorio"] for c in datos["criterios"]):
        errores.append("un caso VERIFICADA necesita al menos un criterio obligatorio")
    if datos["revisado"] and not (datos["revisado_por"] and datos["fecha_revision"]):
        errores.append("revisado: true exige revisado_por (cargo) y fecha_revision")
    if not datos["revisado"] and (datos["revisado_por"] or datos["fecha_revision"]):
        errores.append("sin revisar no puede tener revisado_por ni fecha_revision")
    p = datos["paciente"]
    if p["fuente"] == "ficticio":
        if "datos_ficticios" not in p:
            errores.append("un paciente ficticio necesita datos_ficticios")
        if not p["dni_ficticio"].startswith(PREFIJO_FICTICIO):
            errores.append(f"el DNI ficticio debe empezar con {PREFIJO_FICTICIO}")
    else:
        if "datos_ficticios" in p:
            errores.append("un paciente de seed_demo no lleva datos_ficticios")
        if p["dni_ficticio"] not in _dnis_seed():
            errores.append("el DNI no es de un paciente de seed_demo")
    return errores


def cargar_esquema(dir_conjunto: Path) -> tuple[dict, str]:
    crudo = (dir_conjunto / ESQUEMA).read_bytes()
    return json.loads(crudo), sha256(crudo)


def cargar_conjunto(dir_conjunto: Path = DIR_CONJUNTO_DEFECTO, grupo: str = "piloto",
                    ids: set[str] | None = None) -> Conjunto:
    """Lee y valida todos los casos de <dir_conjunto>/<grupo>. Con errores, no devuelve nada."""
    if grupo not in GRUPOS:
        raise ErrorConjunto(f"Grupo desconocido: {grupo}")
    esquema, huella_esquema = cargar_esquema(dir_conjunto)
    archivos = sorted((dir_conjunto / grupo).glob("*.yaml"))
    if not archivos:
        raise ErrorConjunto(f"No hay casos en {dir_conjunto / grupo}")
    casos, huellas, errores, vistos = [], {}, [], set()
    for ruta in archivos:
        crudo = ruta.read_bytes()
        huellas[ruta.name] = sha256(crudo)
        try:
            datos = yaml.safe_load(crudo.decode("utf-8"))
        except yaml.YAMLError as e:
            errores.append(f"{ruta.name}: YAML inválido ({e})")
            continue
        problemas = validar_caso(datos, esquema, grupo)
        errores += [f"{ruta.name}: {p}" for p in problemas]
        if problemas:
            continue
        if datos["id"] in vistos:
            errores.append(f"{ruta.name}: id repetido {datos['id']}")
        vistos.add(datos["id"])
        casos.append(Caso(datos["id"], ruta.name, huellas[ruta.name], datos))
    if errores:
        raise ErrorConjunto("Casos inválidos:\n" + "\n".join(errores))
    # La huella cubre todos los archivos de la carpeta, aunque se elija un subconjunto.
    huella = huella_conjunto(huellas)
    if ids:
        desconocidos = ids - {c.id for c in casos}
        if desconocidos:
            raise ErrorConjunto(f"Casos inexistentes: {', '.join(sorted(desconocidos))}")
        casos = [c for c in casos if c.id in ids]
    return Conjunto(grupo, casos, huella, huella_esquema, huellas)
