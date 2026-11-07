"""Servicio de modelos con el motor falso: sin PyTorch ni pesos descargados."""
import asyncio
import json
import math
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import exportar_onnx, onnx_int8
from app.catalogo import EMBEDDINGS, RERANKER, cargar_catalogo
from app.config import cargar_config
from app.main import CANDIDATOS_CALENTAMIENTO, MAX_CANDIDATOS, MAX_CARACTERES, MAX_TEXTOS, MIN_LONGITUD_RERANKER, crear_app
from app.motor import crear_motor
from app.motor_falso import DIMENSION, MotorFalso


@pytest.fixture
def cliente():
    with TestClient(crear_app(MotorFalso())) as c:
        yield c


def test_salud(cliente):
    r = cliente.get("/salud")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok" and r.json()["motor"] == "falso"


def test_embeddings_normalizados_de_1024_dimensiones(cliente):
    r = cliente.post("/embeddings", json={"textos": ["anemia leve en niño de 14 meses", "dosis de sulfato ferroso"]})
    assert r.status_code == 200
    datos = r.json()
    assert datos["dimension"] == DIMENSION == 1024
    assert len(datos["vectores"]) == 2
    for v in datos["vectores"]:
        assert len(v) == 1024
        assert math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-6)


def test_embeddings_cercanos_para_textos_parecidos(cliente):
    a, b, c = cliente.post("/embeddings", json={"textos": [
        "tratamiento de la anemia con hierro", "tratamiento con hierro de la anemia infantil", "vacuna contra el sarampión",
    ]}).json()["vectores"]
    coseno = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert coseno(a, b) > coseno(a, c)


def test_reranquear_devuelve_un_puntaje_por_candidato_en_orden(cliente):
    r = cliente.post("/reranquear", json={"consulta": "dosis de hierro en anemia",
                                           "candidatos": ["vacunas del calendario", "dosis de hierro para la anemia"]})
    assert r.status_code == 200
    puntajes = r.json()["puntajes"]
    assert len(puntajes) == 2
    assert all(0 <= p <= 1 for p in puntajes)
    assert puntajes[1] > puntajes[0]


def test_reranquear_acepta_una_longitud_maxima_por_peticion(cliente):
    cuerpo = {"consulta": "dosis de hierro", "candidatos": ["dosis de hierro preventivo"], "max_longitud": 256}
    r = cliente.post("/reranquear", json=cuerpo)
    assert r.status_code == 200 and len(r.json()["puntajes"]) == 1


def test_tokens(cliente):
    r = cliente.post("/tokens", json={"textos": ["Hb 9,8 g/dL", "anemia"]})
    assert r.status_code == 200
    assert r.json()["tokens"] == [7, 1]


@pytest.mark.parametrize("ruta, cuerpo", [
    ("/embeddings", {"textos": []}),
    ("/embeddings", {"textos": ["  "]}),
    ("/embeddings", {"textos": ["x"] * (MAX_TEXTOS + 1)}),
    ("/embeddings", {"textos": ["x" * (MAX_CARACTERES + 1)]}),
    ("/tokens", {}),
    ("/reranquear", {"consulta": "", "candidatos": ["a"]}),
    ("/reranquear", {"consulta": "a", "candidatos": []}),
    ("/reranquear", {"consulta": "a", "candidatos": ["b"] * (MAX_CANDIDATOS + 1)}),
    ("/reranquear", {"consulta": "a", "candidatos": ["b"], "max_longitud": MIN_LONGITUD_RERANKER - 1}),
])
def test_rechaza_solicitudes_invalidas(cliente, ruta, cuerpo):
    assert cliente.post(ruta, json=cuerpo).status_code == 422


class _MotorLento(MotorFalso):
    """Registra cuántas inferencias se ejecutan a la vez."""

    def __init__(self):
        self.activas = 0
        self.maximo = 0
        self._candado = threading.Lock()

    def embeddings(self, textos):
        with self._candado:
            self.activas += 1
            self.maximo = max(self.maximo, self.activas)
        time.sleep(0.05)
        with self._candado:
            self.activas -= 1
        return super().embeddings(textos)


@pytest.mark.parametrize("concurrencia", [1, 2])
def test_el_semaforo_limita_las_inferencias_simultaneas(concurrencia):
    motor = _MotorLento()
    app = crear_app(motor, concurrencia=concurrencia)

    async def _varias():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://modelos") as c:
            respuestas = await asyncio.gather(*[c.post("/embeddings", json={"textos": [f"texto {i}"]}) for i in range(6)])
        assert all(r.status_code == 200 for r in respuestas)

    asyncio.run(_varias())
    assert motor.maximo == concurrencia


def test_motor_falso_seleccionado_por_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("MODELOS_MOTOR", "falso")
    with TestClient(crear_app()) as c:
        assert c.get("/salud").json()["motor"] == "falso"


def test_variable_de_motor_invalida(monkeypatch):
    monkeypatch.setenv("MODELOS_MOTOR", "gpu")
    with pytest.raises(ValueError):
        crear_motor(cargar_config())


def test_catalogo_fija_revisiones_exactas():
    catalogo = cargar_catalogo(cargar_config().revisiones)
    assert catalogo[EMBEDDINGS].repositorio == "BAAI/bge-m3" and catalogo[EMBEDDINGS].dimension == 1024
    assert catalogo[RERANKER].repositorio == "BAAI/bge-reranker-v2-m3"
    for modelo in catalogo.values():
        assert len(modelo.revision) == 40
        assert not any(a.startswith("onnx/") or a.endswith(".pt") for a in modelo.archivos)


def test_catalogo_rechaza_revisiones_que_no_son_hash(tmp_path):
    ruta = tmp_path / "revisiones.json"
    ruta.write_text(json.dumps({
        EMBEDDINGS: {"repositorio": "BAAI/bge-m3", "revision": "main", "archivos": ["config.json"],
                     "dimension": 1024, "tamano_aproximado_mb": 1},
        RERANKER: {"repositorio": "BAAI/bge-reranker-v2-m3", "revision": "a" * 40, "archivos": ["config.json"],
                   "dimension": None, "tamano_aproximado_mb": 1},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="hash completo"):
        cargar_catalogo(ruta)


class _MotorRegistrado(MotorFalso):
    """Registra las inferencias para comprobar el calentamiento."""

    def __init__(self):
        self.llamadas = []

    def embeddings(self, textos):
        self.llamadas.append(("embeddings", len(textos), None))
        return super().embeddings(textos)

    def reranquear(self, consulta, candidatos, max_longitud=None):
        self.llamadas.append(("reranquear", len(candidatos), max_longitud))
        return super().reranquear(consulta, candidatos, max_longitud)


def test_calienta_ambos_modelos_antes_de_atender(monkeypatch):
    monkeypatch.setenv("MODELOS_LONGITUD_CALENTAMIENTO", "256")
    motor = _MotorRegistrado()
    app = crear_app(motor)
    assert motor.llamadas == []
    with TestClient(app) as c:
        assert motor.llamadas == [("embeddings", 1, None), ("reranquear", CANDIDATOS_CALENTAMIENTO, 256)]
        arranque = c.get("/salud").json()["arranque"]
    assert set(arranque["calentamiento_ms"]) == {"embedding_ms", "reranker_ms"}
    assert arranque["total_ms"] >= arranque["carga_ms"]


def test_reranker_por_defecto_onnx_int8_y_fp32_seleccionable(monkeypatch):
    monkeypatch.delenv("MODELOS_RERANKER", raising=False)
    assert cargar_config().reranker == "onnx-int8"
    monkeypatch.setenv("MODELOS_RERANKER", "fp32")
    assert cargar_config().reranker == "fp32"
    monkeypatch.setenv("MODELOS_RERANKER", "int4")
    with pytest.raises(ValueError, match="MODELOS_RERANKER"):
        cargar_config()


def _exportacion_simulada(dir_onnx, modelo, **cambios):
    carpeta = onnx_int8.carpeta(dir_onnx)
    carpeta.mkdir(parents=True)
    (carpeta / onnx_int8.ARCHIVO).write_bytes(b"onnx simulado")
    manifiesto = {"repositorio": modelo.repositorio, "revision": modelo.revision,
                  "sha256": onnx_int8.sha256(carpeta / onnx_int8.ARCHIVO)} | cambios
    (carpeta / onnx_int8.MANIFIESTO).write_text(json.dumps(manifiesto), encoding="utf-8")


def _reranker_fijado():
    return cargar_catalogo(cargar_config().revisiones)[RERANKER]


def test_onnx_valido_de_la_revision_fijada(tmp_path):
    modelo = _reranker_fijado()
    _exportacion_simulada(tmp_path, modelo)
    assert onnx_int8.comprobar(tmp_path, modelo)["revision"] == modelo.revision


@pytest.mark.parametrize("cambios, mensaje", [
    (None, "exportar-onnx"),
    ({"revision": "b" * 40}, "revisión fijada"),
    ({"sha256": "0" * 64}, "SHA-256"),
])
def test_onnx_ausente_de_otra_revision_o_alterado(tmp_path, cambios, mensaje):
    modelo = _reranker_fijado()
    if cambios is not None:
        _exportacion_simulada(tmp_path, modelo, **cambios)
    with pytest.raises(RuntimeError, match=mensaje):
        onnx_int8.comprobar(tmp_path, modelo)


def test_exportar_no_repite_una_exportacion_valida(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MODELOS_DIR_ONNX", str(tmp_path))
    _exportacion_simulada(tmp_path, _reranker_fijado())
    monkeypatch.setattr(exportar_onnx, "exportar", lambda *a: pytest.fail("no debía exportar"))
    assert exportar_onnx.main([]) == 0
    assert "ya está exportado" in capsys.readouterr().out
