"""Errores del pipeline de indexación."""


class ErrorIndexacion(Exception):
    """Fallo que deja el documento en ERROR con un mensaje para la pantalla M11."""


class ErrorAncla(ErrorIndexacion):
    """Un ancla de texto no aparece exactamente una vez donde se espera."""
