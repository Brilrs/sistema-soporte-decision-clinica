"""Procesamiento de la consulta y recuperación híbrida (secciones 4.2 y 4.3).

Cada módulo recibe la sesión de base de datos como parámetro, para que el
orquestador elija en cada nodo la conexión que corresponde: la validación y la
clasificación usan la de cdss_clinica; el filtro de dominio, la normalización y la
recuperación, la de cdss_generacion. Ningún módulo lee
asistencia.consulta.texto_consulta ni clinico.tamizaje.observaciones."""
