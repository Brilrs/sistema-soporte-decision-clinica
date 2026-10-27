"""Cálculos de fechas compartidos."""
from datetime import date, datetime, timedelta, timezone

# Perú no aplica horario de verano: UTC-5 todo el año. Se fija aquí para que
# "hoy" no dependa de la zona horaria del contenedor (UTC en Docker y Azure).
ZONA_PERU = timezone(timedelta(hours=-5), "America/Lima")


def hoy() -> date:
    """Fecha actual en Perú."""
    return datetime.now(ZONA_PERU).date()


def edad_en_meses(fecha_nacimiento: date, fecha_referencia: date) -> int:
    """Meses cumplidos entre dos fechas (un mes se cumple el mismo día del mes siguiente).
    Ejemplo: 12/07/2025 -> 26/09/2026 = 14 meses."""
    if fecha_referencia < fecha_nacimiento:
        raise ValueError("La fecha de referencia es anterior al nacimiento")
    meses = (fecha_referencia.year - fecha_nacimiento.year) * 12 + (fecha_referencia.month - fecha_nacimiento.month)
    if fecha_referencia.day < fecha_nacimiento.day:
        meses -= 1
    return meses
