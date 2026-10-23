"""Contraseñas (Argon2id), tokens JWT y hash HMAC de identificadores."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

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


def crear_token(id_usuario: str, rol: str) -> tuple[str, int]:
    s = get_settings()
    ahora = datetime.now(timezone.utc)
    segundos = s.jwt_minutos * 60
    payload = {"sub": id_usuario, "rol": rol, "iat": ahora, "exp": ahora + timedelta(seconds=segundos)}
    return jwt.encode(payload, s.jwt_secreto, algorithm="HS256"), segundos


def leer_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si el token es inválido o venció."""
    return jwt.decode(token, get_settings().jwt_secreto, algorithms=["HS256"])


def hmac_identificador(valor: str) -> str:
    """HMAC-SHA256 de un DNI o número de historia clínica normalizado.
    Permite la búsqueda exacta sin guardar ni descifrar el valor."""
    normalizado = "".join(valor.split()).upper()
    return hmac.new(get_settings().clave_hmac.encode(), normalizado.encode(), hashlib.sha256).hexdigest()
