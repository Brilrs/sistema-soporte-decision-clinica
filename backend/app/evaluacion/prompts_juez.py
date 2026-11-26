"""Prompts y esquemas de salida de los juicios propios (docs/diseno_evaluacion_oe3.md, sección 3).

El juez recibe solo datos sintéticos: la consulta filtrada, la respuesta del sistema, el texto de
los fragmentos enviados y las afirmaciones clave del caso. Los prompts de RAGAS son los de la
biblioteca (en inglés) y no se tocan. Cambiar un texto de aquí cambia su SHA-256, que va en el
informe: no se cambian después de congelar."""
import hashlib
import json

VERSION = "1"

AFIRMACIONES = "afirmaciones"
ADHERENCIA = "adherencia"

SISTEMA_AFIRMACIONES = """Eres un evaluador de un sistema de apoyo a la decisión clínica sobre anemia infantil.
Recibes una consulta, la respuesta del sistema, los fragmentos de guías que el sistema recibió
(cada uno con su etiqueta F-01, F-02...) y una lista numerada de afirmaciones clave de referencia.
Todos los datos son sintéticos.

Tareas:
1. Divide la respuesta en afirmaciones clínicas simples (una idea por afirmación: una dosis, un
   plazo, un control, una derivación, una clasificación). Ignora frases de cortesía.
2. Para cada afirmación de la respuesta:
   - "clave": el índice (desde 0) de la afirmación clave de referencia que expresa lo mismo, o
     null si no corresponde a ninguna;
   - "fragmentos": las etiquetas de los fragmentos que la sustentan, es decir, de los que se puede
     inferir sin conocimiento externo. Lista vacía si ninguno la sustenta.
3. Para cada afirmación clave de referencia (por índice): "presente" si la respuesta la expresa,
   aunque sea con otras palabras, y "contradicha" si la respuesta dice algo incompatible con ella.

Responde solo con el JSON pedido."""

SISTEMA_ADHERENCIA = """Eres un evaluador de un sistema de apoyo a la decisión clínica sobre anemia infantil.
Recibes una consulta, la respuesta del sistema y los fragmentos de guías que el sistema recibió.
Todos los datos son sintéticos.

Pregunta: ¿en qué medida el contenido clínico de la respuesta proviene de los fragmentos enviados,
y no del conocimiento propio del modelo? No juzgues si la respuesta es correcta, sino de dónde sale.

Escala de 0 a 1 (usa valores intermedios con dos decimales):
- 1,0: todas las indicaciones clínicas (dosis, plazos, controles, criterios, derivación) se apoyan
  en los fragmentos, y la respuesta usa la información pertinente que traen.
- 0,7: casi todas las indicaciones clínicas se apoyan en los fragmentos; lo que no se apoya es
  general y no cambia la conducta clínica.
- 0,4: mezcla: alguna indicación clínica importante no está en los fragmentos, o la respuesta
  ignora un fragmento pertinente y responde con otra información.
- 0,0: la respuesta no usa los fragmentos, o los contradice.
Si la respuesta solo declara que la evidencia es insuficiente, puntúa según si los fragmentos
traían o no la información pedida: alto si de verdad no la traían, bajo si la traían.

Devuelve "puntaje", "indicaciones_sin_respaldo" (las indicaciones clínicas que no se apoyan en
ningún fragmento) y una "justificacion" breve. Responde solo con el JSON pedido."""

ESQUEMA_AFIRMACIONES = {
    "type": "object",
    "additionalProperties": False,
    "required": ["afirmaciones", "claves"],
    "properties": {
        "afirmaciones": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["texto", "clave", "fragmentos"],
            "properties": {"texto": {"type": "string"}, "clave": {"type": ["integer", "null"]},
                           "fragmentos": {"type": "array", "items": {"type": "string"}}}}},
        "claves": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["indice", "presente", "contradicha"],
            "properties": {"indice": {"type": "integer"}, "presente": {"type": "boolean"},
                           "contradicha": {"type": "boolean"}}}},
    },
}

ESQUEMA_ADHERENCIA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["puntaje", "indicaciones_sin_respaldo", "justificacion"],
    "properties": {"puntaje": {"type": "number"},
                   "indicaciones_sin_respaldo": {"type": "array", "items": {"type": "string"}},
                   "justificacion": {"type": "string"}},
}

# Para los prompts de RAGAS: el texto de la tarea viene en el prompt de la biblioteca.
SISTEMA_RAGAS = "You are an evaluator. All data is synthetic. Answer only with JSON that follows the given schema."


def contenido(consulta: str, respuesta: str, fragmentos: list[dict], afirmaciones_clave: list[str] | None = None) -> str:
    """Entrada del juez en JSON. `fragmentos` lleva solo etiqueta y texto."""
    datos = {"consulta": consulta, "respuesta": respuesta,
             "fragmentos": [{"etiqueta": f["etiqueta"], "texto": f["texto"]} for f in fragmentos]}
    if afirmaciones_clave is not None:
        datos["afirmaciones_clave"] = [{"indice": i, "texto": t} for i, t in enumerate(afirmaciones_clave)]
    return json.dumps(datos, ensure_ascii=False, sort_keys=True)


def huellas() -> dict[str, str]:
    """SHA-256 de cada texto, para el informe."""
    textos = {"sistema_afirmaciones": SISTEMA_AFIRMACIONES, "sistema_adherencia": SISTEMA_ADHERENCIA,
              "sistema_ragas": SISTEMA_RAGAS,
              "esquema_afirmaciones": json.dumps(ESQUEMA_AFIRMACIONES, sort_keys=True),
              "esquema_adherencia": json.dumps(ESQUEMA_ADHERENCIA, sort_keys=True)}
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in textos.items()}
