"""Reglas de plausibilidad de la edición de parámetros (M12, parte E1b del Sprint 3).

Por validar con el asesor: los límites duros y los umbrales de advertencia de este módulo son una
propuesta del equipo (diagnóstico de la fase 0 de E1), no valores de la norma. Los valores vigentes
sembrados pasan todas estas reglas (lo comprueba tests/test_e1b_parametros.py). Cambiarlos es un
cambio de código con su prueba, nunca desde M12."""
from decimal import Decimal

# --- Errores duros (422) ------------------------------------------------------
HB_MIN_PLAUSIBLE = Decimal("2.0")        # g/dL
HB_MAX_PLAUSIBLE = Decimal("20.0")       # g/dL
PASO_HB = Decimal("0.1")                 # un decimal: los límites contiguos se separan en 0.1
AJUSTE_MIN = Decimal("0.0")              # g/dL que se restan
AJUSTE_MAX = Decimal("6.0")
PASO_AJUSTE = Decimal("0.1")
COBERTURA_MINIMA_ALTITUD = 4380          # msnm: altitud máxima del catálogo de distritos (Chaupimarca)
VIGENCIA_MIN_DIAS = 7
VIGENCIA_MAX_DIAS = 90

# --- Advertencias que exigen confirmacion_escrita = «CONFIRMO» ----------------
CONFIRMACION = "CONFIRMO"
CAMBIO_HB_ADVERTENCIA = Decimal("1.0")           # cambio de un límite de Hb respecto del vigente
SIN_ANEMIA_MIN_ADVERTENCIA = Decimal("10.0")     # punto de corte de «sin anemia» fuera de este rango
SIN_ANEMIA_MAX_ADVERTENCIA = Decimal("12.0")
CAMBIO_AJUSTE_ADVERTENCIA = Decimal("0.5")       # cambio de un ajuste respecto del vigente
VIGENCIA_ADVERTENCIA_DIAS = 60                   # vigencia mayor que esto
