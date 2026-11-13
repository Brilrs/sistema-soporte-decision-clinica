"""Parte E0: fixtures NDJSON del contrato de consultas para el frontend (parte E).

Genera, por HTTP y con el cliente falso del modelo de lenguaje, el flujo completo de los 7
estados finales y el resultado guardado (GET) de cada uno, y los escribe en
frontend/src/__fixtures__. Solo datos sintéticos: pacientes de seed_demo y la guía de prueba.

- La prueba falla si un evento no cumple el contrato (EventoConsulta, ResultadoConsulta) o si
  fin, error, en_cola o el resultado traen un campo que el contrato no declara.
- Si el contrato cambia de forma compatible, el diff de los fixtures lo muestra.
- Para que el diff solo muestre cambios del contrato, se normalizan los valores que cambian
  en cada corrida: los UUID (en orden de aparición), los tiempos (*_ms) y las fechas. En el
  resultado guardado, la vigencia y su mensaje se copian del evento fin, porque el GET los
  calcula con la fecha del día y el stream con la fecha de referencia de los casos."""
import json
import re
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.api.routes import consultas as rutas
from app.rag import grafo as g
from app.rag.cliente_llm import TIEMPO_AGOTADO
from app.rag.filtro_texto import IdentidadPaciente, generar_huellas
from app.scripts.seed_demo import PACIENTES
from tests.test_d1_grafo import _caso, _ids, entorno  # noqa: F401 (fixtures)
from tests.test_d2_api import _caso_http, _consultar, _cuerpo, cliente_http, consultas_d2, usar_entorno  # noqa: F401
from tests.test_generacion_bd import engine_clinica, engine_generacion, guia  # noqa: F401 (fixtures)

DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "__fixtures__"
EVENTO = TypeAdapter(rutas.EventoConsulta)
MODELOS_SIN_EXTRAS = {"fin": rutas.EventoFin, "error": rutas.EventoError, "en_cola": rutas.EventoEnCola}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FECHA_FIJA = "2026-10-20T10:00:00-05:00"
IDENTIDAD = [p[0] for p in PACIENTES] + [p[1] for p in PACIENTES] + [p[2] for p in PACIENTES] + \
    [parte for p in PACIENTES for parte in p[0].split()]


def normalizar(eventos: list[dict], resultado: dict) -> tuple[list[dict], dict]:
    fin = eventos[-1]
    resultado = {**resultado, "vigencia": fin.get("vigencia", resultado.get("vigencia"))}
    if resultado["estado"] == "TAMIZAJE_NO_VIGENTE":
        resultado["mensaje"] = fin["mensaje"]
    texto = json.dumps({"eventos": eventos, "resultado": resultado}, ensure_ascii=False)
    ids: dict[str, str] = {}
    for u in _UUID.findall(texto):
        ids.setdefault(u, f"00000000-0000-4000-8000-{len(ids) + 1:012d}")
    texto = _UUID.sub(lambda m: ids[m.group()], texto)
    datos = json.loads(texto)

    def tiempos(valor, clave="", padre=""):
        if isinstance(valor, dict):
            return {k: tiempos(v, k, clave) for k, v in valor.items()}
        if isinstance(valor, list):
            return [tiempos(v, clave, padre) for v in valor]
        es_tiempo = clave == "ms" or clave.endswith("_ms") or padre in ("por_nodo", "espera_ms")
        if isinstance(valor, (int, float)) and not isinstance(valor, bool) and es_tiempo:
            return 100
        if clave.startswith("fecha_hora") or clave == "fecha_registro":
            return None if valor is None else FECHA_FIJA
        return valor
    eventos = [{**tiempos(e), **({"transcurrido_ms": 100 * i} if "transcurrido_ms" in e else {})}
               for i, e in enumerate(datos["eventos"], start=1)]
    return eventos, tiempos(datos["resultado"])


def _validar(eventos: list[dict], resultado: dict) -> None:
    for e in eventos:
        EVENTO.validate_python(e)
        modelo = MODELOS_SIN_EXTRAS.get(e["tipo"])
        if modelo is not None:
            assert set(e) <= set(modelo.model_fields), (e["tipo"], set(e) - set(modelo.model_fields))
    rutas.ResultadoConsulta.model_validate(resultado)
    assert set(resultado) <= set(rutas.ResultadoConsulta.model_fields), \
        set(resultado) - set(rutas.ResultadoConsulta.model_fields)


def _escribir(nombre: str, eventos: list[dict], resultado: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"consulta_{nombre}.ndjson").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in eventos), encoding="utf-8", newline="\n")
    (DIR / f"resultado_{nombre}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8", newline="\n")


# (estado, caso, cambios en el cuerpo, modos del cliente falso o None para los del caso, bloquear)
FLUJOS = [
    ("VERIFICADA", "l", {}, None, False),
    ("EVIDENCIA_INSUFICIENTE", "j", {}, None, False),
    ("ERROR", "b", {}, [TIEMPO_AGOTADO], False),
    ("DATOS_FALTANTES", "g", {}, None, False),
    ("FUERA_DE_DOMINIO", "h", {}, None, False),
    ("TAMIZAJE_NO_VIGENTE", "f", {"confirma_tamizaje_no_vigente": False}, None, False),
    ("SOLICITUD_BLOQUEADA", "b", {}, None, True),
]


@pytest.mark.parametrize("estado, id_caso, cambios, modos, bloquear", FLUJOS, ids=[f[0] for f in FLUJOS])
def test_genera_los_fixtures_ndjson_de_cada_estado(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno,
                                                    monkeypatch, estado, id_caso, cambios, modos, bloquear):
    if bloquear:
        monkeypatch.setattr(g, "generar_huellas", lambda _: generar_huellas(IdentidadPaciente("Ana Ferroso", "1", "2")))
    if modos is None:
        eventos = _caso_http(cliente_http, cabeceras, consultas_d2, super_engine, usar_entorno, id_caso, **cambios)[1]
    else:
        caso = _caso(id_caso)
        id_paciente, id_tamizaje, _ = _ids(super_engine, caso)
        usar_entorno(modos)
        eventos = _consultar(cliente_http, cabeceras, consultas_d2, id_paciente,
                             _cuerpo(caso, id_tamizaje=id_tamizaje, **cambios))[1]
    assert eventos[-1]["estado"] == estado
    resultado = cliente_http.get(f"/api/consultas/{eventos[-1]['id_consulta']}", headers=cabeceras("med.salazar")).json()
    _validar(eventos, resultado)
    eventos, resultado = normalizar(eventos, resultado)
    _validar(eventos, resultado)
    volcado = json.dumps({"e": eventos, "r": resultado}, ensure_ascii=False)
    for dato in IDENTIDAD:
        assert dato not in volcado, dato
    if estado == "VERIFICADA":
        ingles = [c for c in eventos[-1]["citas"] if c["idioma"] == "en"]
        assert ingles and ingles[0]["extracto_traducido"] and ingles[0]["etiqueta_traduccion"]
        assert resultado["citas"] == eventos[-1]["citas"]
    _escribir(estado.lower(), eventos, resultado)


def test_normalizacion_estable_de_ids_tiempos_y_fechas():
    eventos = [{"tipo": "etapa", "etapa": "validar", "ms": 12, "transcurrido_ms": 15,
                "id_consulta": "7c1e2f3a-0000-4000-8000-abcdefabcdef"},
               {"tipo": "fin", "id_consulta": "7c1e2f3a-0000-4000-8000-abcdefabcdef", "vigencia": {"dias": 3},
                "tiempos_ms": {"total_ms": 9, "por_nodo": {"validar": 12}}, "transcurrido_ms": 40}]
    resultado = {"estado": "VERIFICADA", "fecha_hora_inicio": "2026-11-14T08:00:00", "vigencia": {"dias": 9}}
    e, r = normalizar(eventos, resultado)
    assert e[0]["id_consulta"] == e[1]["id_consulta"] == "00000000-0000-4000-8000-000000000001"
    assert (e[0]["ms"], e[0]["transcurrido_ms"], e[1]["transcurrido_ms"]) == (100, 100, 200)
    assert e[1]["tiempos_ms"] == {"total_ms": 100, "por_nodo": {"validar": 100}}
    assert r["fecha_hora_inicio"] == FECHA_FIJA and r["vigencia"] == {"dias": 3}
