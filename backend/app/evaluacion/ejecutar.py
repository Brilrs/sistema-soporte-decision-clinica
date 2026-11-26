"""Ejecución de los casos con el grafo real de la consulta (app/services/consultas.py), una sola vez.

- Crea los pacientes ficticios del conjunto (DNI con prefijo 89, nombre sintético, sin datos reales)
  con la conexión clínica y los clasifica con el mismo servicio que el sistema.
- Ejecuta cada caso con su fecha de referencia y guarda en ejecucion.jsonl el id de la consulta, el
  estado y los eventos sin texto. Si la carpeta ya tiene una ejecución, no vuelve a ejecutar.
- Cliente del modelo de lenguaje: el falso del proyecto por omisión. El real exige confirmar que
  los datos son sintéticos y nunca se usa con el piloto (opción A del diseño, sección 5.1).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.core.fechas import edad_en_meses
from app.core.seguridad import hmac_identificador
from app.evaluacion.dataset import Caso, Conjunto

USUARIO_CONSULTA = "med.salazar"
USUARIO_REGISTRO = "enf.rojas"
ARCHIVO_EJECUCION = "ejecucion.jsonl"


class ErrorEjecucion(Exception):
    """La ejecución no se puede hacer (ya existe, cliente no permitido o paciente inexistente)."""


_CONSONANTES, _VOCALES = "bcdfgjklmnprstvz", "aeiou"


def nombre_ficticio(id_caso: str) -> str:
    """Nombre sintético y determinista de tres pseudopalabras (consonante y vocal alternadas). No
    puede llevar palabras comunes: el control previo de la solicitud (app/rag/proteccion.py) compara
    cada palabra de la solicitud con las partes del nombre, y un nombre como «Paciente de
    evaluación» bloquea la consulta (la clave «paciente» está en toda solicitud)."""
    cifra = hashlib.sha256(f"oe3-ficticio:{id_caso}".encode()).digest()
    partes = []
    for p in range(3):
        letras = [(_CONSONANTES if i % 2 == 0 else _VOCALES)[cifra[p * 7 + i] % (16 if i % 2 == 0 else 5)]
                  for i in range(7)]
        partes.append("".join(letras).capitalize())
    return " ".join(partes)


def cliente_para(caso: Caso, llm: str, falso_segun_esperado: bool = False, confirmo: bool = False,
                 grupo: str = "piloto"):
    from app.rag.cliente_llm import APROBADA, EVIDENCIA_INSUFICIENTE, ClienteAnthropic, ClienteFalso
    if llm == "falso":
        modo = EVIDENCIA_INSUFICIENTE if falso_segun_esperado and caso["estado_esperado"] == "EVIDENCIA_INSUFICIENTE" \
            else APROBADA
        return ClienteFalso(modos=[modo], preferir_ingles="fragmento_en_ingles" in caso["tipos"])
    if llm == "real":
        if grupo == "piloto":
            raise ErrorEjecucion("El piloto se prueba solo con el cliente falso (opción A del diseño)")
        if not confirmo:
            raise ErrorEjecucion("--llm real exige --confirmo-datos-sinteticos")
        return ClienteAnthropic()
    raise ErrorEjecucion(f"Cliente desconocido: {llm}")


def preparar_ficticios(motor_clinica: Engine, casos: list[Caso]) -> list[str]:
    """Crea los pacientes ficticios que falten. Devuelve los ids de caso creados."""
    from app.services.clasificacion import clasificar, guardar_resultado
    clave = get_settings().clave_pii
    creados = []
    with motor_clinica.begin() as c:
        usuario = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :u"),
                            {"u": USUARIO_REGISTRO}).scalar_one()
        sintomas = dict(c.execute(text("SELECT nombre, id_sintoma FROM clinico.sintoma")).all())
        for caso in casos:
            p = caso["paciente"]
            if p["fuente"] != "ficticio":
                continue
            if c.execute(text("SELECT 1 FROM clinico.paciente_identidad WHERE dni_hash = :h"),
                         {"h": hmac_identificador(p["dni_ficticio"])}).first():
                continue
            d = p["datos_ficticios"]
            t = d["tamizaje"]
            id_paciente = c.execute(text(
                """INSERT INTO clinico.paciente (ubigeo_residencia, fecha_nacimiento, sexo, edad_gestacional_nacer,
                                                 bajo_peso_nacer, registrado_por)
                   VALUES (:ub, :nac, :sx, :eg, :bp, CAST(:u AS uuid)) RETURNING id_paciente::text"""),
                {"ub": d["ubigeo"], "nac": d["fecha_nacimiento"], "sx": d["sexo"], "eg": d["edad_gestacional"],
                 "bp": d["bajo_peso_al_nacer"], "u": usuario}).scalar_one()
            hc = f"EV{p['dni_ficticio'][-5:]}"
            c.execute(text(
                """INSERT INTO clinico.paciente_identidad (id_paciente, nombres_apellidos_cifrado, dni_cifrado, dni_hash,
                                                           numero_hc_cifrado, numero_hc_hash, direccion_cifrada)
                   VALUES (CAST(:id AS uuid), pgp_sym_encrypt(:nom, :k, 'cipher-algo=aes256'),
                           pgp_sym_encrypt(:dni, :k, 'cipher-algo=aes256'), :dh,
                           pgp_sym_encrypt(:hc, :k, 'cipher-algo=aes256'), :hh,
                           pgp_sym_encrypt(:dir, :k, 'cipher-algo=aes256'))"""),
                {"id": id_paciente, "nom": nombre_ficticio(caso.id), "dni": p["dni_ficticio"],
                 "dh": hmac_identificador(p["dni_ficticio"]), "hc": hc, "hh": hmac_identificador(hc),
                 "dir": "Dirección ficticia", "k": clave})
            id_tamizaje = c.execute(text(
                """INSERT INTO clinico.tamizaje (id_paciente, id_usuario, fecha_tamizaje, edad_meses, hemoglobina_g_dl,
                                                 metodo_medicion, peso_kg, talla_cm, recibe_suplementacion_hierro,
                                                 lactancia_materna_actual, parasitosis_reciente, observaciones)
                   VALUES (CAST(:p AS uuid), CAST(:u AS uuid), :f, :e, :hb, 'HEMOGLOBINOMETRO', :peso, :talla, :sup,
                           :lac, :par, NULL) RETURNING id_tamizaje::text"""),
                {"p": id_paciente, "u": usuario, "f": p["fecha_tamizaje"],
                 "e": edad_en_meses(d["fecha_nacimiento"], p["fecha_tamizaje"]), "hb": t["hemoglobina_g_dl"],
                 "peso": t["peso_kg"], "talla": t["talla_cm"], "sup": t["recibe_suplementacion_hierro"],
                 "lac": t["lactancia_materna_actual"], "par": t["parasitosis"]}).scalar_one()
            for s in t["sintomas"]:
                c.execute(text("INSERT INTO clinico.tamizaje_sintoma (id_tamizaje, id_sintoma) VALUES (CAST(:t AS uuid), :s)"),
                          {"t": id_tamizaje, "s": sintomas[s]})
            if t["hemoglobina_g_dl"] is not None:
                altitud = c.execute(text("SELECT altitud_msnm FROM clinico.distrito WHERE ubigeo = :u"),
                                    {"u": d["ubigeo"]}).scalar_one()
                evaluacion = clasificar(c, t["hemoglobina_g_dl"],
                                        edad_en_meses(d["fecha_nacimiento"], p["fecha_tamizaje"]), altitud)
                if evaluacion.clasificacion is not None:
                    guardar_resultado(c, id_tamizaje, evaluacion.clasificacion)
            creados.append(caso.id)
    return creados


def _ids(c, caso: Caso) -> tuple[str, str]:
    p = caso["paciente"]
    fila = c.execute(text(
        """SELECT t.id_paciente::text, t.id_tamizaje::text FROM clinico.tamizaje t
             JOIN clinico.paciente_identidad i ON i.id_paciente = t.id_paciente
            WHERE i.dni_hash = :h AND t.fecha_tamizaje = :f"""),
        {"h": hmac_identificador(p["dni_ficticio"]), "f": p["fecha_tamizaje"]}).first()
    if fila is None:
        raise ErrorEjecucion(f"No existe el tamizaje del caso {caso.id} (seed_demo o preparar)")
    return fila[0], fila[1]


def _sin_texto(evento: dict) -> dict:
    return {k: v for k, v in evento.items() if k not in ("recomendacion", "citas", "clasificacion", "mensaje")}


def ejecutar(conjunto: Conjunto, entorno_base, salida: Path, llm: str = "falso", falso_segun_esperado: bool = False,
             confirmo: bool = False) -> list[dict]:
    """Ejecuta los casos y escribe <salida>/ejecucion.jsonl. Una sola vez por carpeta."""
    from app.services import consultas as srv
    archivo = salida / ARCHIVO_EJECUCION
    if archivo.exists():
        raise ErrorEjecucion(f"{archivo} ya existe: el sistema se ejecuta una sola vez por corrida")
    clientes = {caso.id: cliente_para(caso, llm, falso_segun_esperado, confirmo, conjunto.grupo)
                for caso in conjunto.casos}
    with entorno_base.clinica.connect() as c:
        usuario = c.execute(text("SELECT id_usuario::text FROM seguridad.usuario WHERE nombre_usuario = :u"),
                            {"u": USUARIO_CONSULTA}).scalar_one()
        solicitudes = {}
        for caso in conjunto.casos:
            id_paciente, id_tamizaje = _ids(c, caso)
            solicitudes[caso.id] = srv.SolicitudConsulta(
                id_paciente, usuario, caso["consulta"], id_tamizaje,
                bool(caso["paciente"].get("confirma_tamizaje_no_vigente", False)))
    salida.mkdir(parents=True, exist_ok=True)
    filas = []
    for caso in conjunto.casos:
        entorno = replace(entorno_base, cliente=clientes[caso.id], fecha_referencia=caso["fecha_referencia"])
        inicio = time.perf_counter()
        eventos = asyncio.run(srv.eventos_de(solicitudes[caso.id], entorno))
        fin = eventos[-1]
        fila = {"id_caso": caso.id, "id_consulta": fin.get("id_consulta"), "estado": fin.get("estado"),
                "estado_esperado": caso["estado_esperado"], "llm": llm, "modo_prueba": fin.get("modo_prueba"),
                "total_ms": round((time.perf_counter() - inicio) * 1000),
                "eventos": [_sin_texto(e) for e in eventos]}
        filas.append(fila)
        with archivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
    return filas
