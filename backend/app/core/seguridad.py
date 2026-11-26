"""Contraseñas (Argon2id), tokens JWT y hash HMAC de identificadores."""
import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id con parámetros recomendados por la librería


def hash_contrasena(contrasena: str) -> str:
    return _hasher.hash(contrasena)


def verificar_contrasena(hash_guardado: str, contrasena: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, contrasena)
    except (VerifyMismatchError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _hash_ficticio() -> str:
    """Hash Argon2id de una clave aleatoria que nadie conoce (se crea una vez por proceso)."""
    return _hasher.hash(secrets.token_urlsafe(32))


def verificar_contrasena_ficticia(contrasena: str) -> bool:
    """Comprueba la contraseña contra el hash ficticio, siempre False. El inicio de sesión de un usuario
    que no existe tarda así lo mismo que el de una cuenta con la clave equivocada (fila 168)."""
    verificar_contrasena(_hash_ficticio(), contrasena)
    return False


def texto_politica() -> str:
    """La política escrita, igual en los mensajes de error y en la pantalla de cambio."""
    return f"Mínimo {get_settings().contrasena_longitud_minima} caracteres, con al menos una letra y un número"


def cumple_politica(contrasena: str) -> bool:
    """Longitud mínima configurable (CONTRASENA_LONGITUD_MINIMA), al menos una letra y un número."""
    return (len(contrasena) >= get_settings().contrasena_longitud_minima
            and any(c.isalpha() for c in contrasena) and any(c.isdigit() for c in contrasena))


# Sin caracteres que se confunden al leerlos en pantalla (0/O, 1/l/I)
_ALFABETO = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI") + "#%+=?@"
_LONGITUD_GENERADA = 16


def generar_contrasena() -> str:
    """Contraseña aleatoria (módulo secrets) que cumple la política. El administrador nunca la escribe:
    el sistema la genera al crear la cuenta o al restablecerla y la muestra una sola vez."""
    longitud = max(_LONGITUD_GENERADA, get_settings().contrasena_longitud_minima)
    while True:
        contrasena = "".join(secrets.choice(_ALFABETO) for _ in range(longitud))
        if cumple_politica(contrasena):
            return contrasena


def crear_token(id_usuario: str, rol: str, version_sesion: int) -> tuple[str, int]:
    """El token lleva la versión de sesión de la cuenta (sv): deja de valer cuando la versión sube
    (contraseña cambiada o restablecida, cuenta reactivada)."""
    s = get_settings()
    ahora = datetime.now(timezone.utc)
    segundos = s.jwt_minutos * 60
    payload = {"sub": id_usuario, "rol": rol, "sv": version_sesion, "iat": ahora,
               "exp": ahora + timedelta(seconds=segundos)}
    return jwt.encode(payload, s.jwt_secreto, algorithm="HS256"), segundos


def leer_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si el token es inválido o venció."""
    return jwt.decode(token, get_settings().jwt_secreto, algorithms=["HS256"])


def hmac_identificador(valor: str) -> str:
    """HMAC-SHA256 de un DNI o número de historia clínica normalizado.
    Permite la búsqueda exacta sin guardar ni descifrar el valor."""
    normalizado = "".join(valor.split()).upper()
    return hmac.new(get_settings().clave_hmac.encode(), normalizado.encode(), hashlib.sha256).hexdigest()
