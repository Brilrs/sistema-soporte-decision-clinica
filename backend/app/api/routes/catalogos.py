"""Catálogos para los formularios de registro (M03 y M14)."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import usuario_actual
from app.core.db import sesion_clinica

router = APIRouter(prefix="/api/catalogos", tags=["Catálogos"], dependencies=[Depends(usuario_actual)])


@router.get("/distritos")
def distritos(sesion: Session = Depends(sesion_clinica)) -> list[dict]:
    """Distritos con su altitud de referencia (la altitud del paciente se deriva del distrito)."""
    return [dict(f) for f in sesion.execute(text(
        """SELECT ubigeo, nombre, provincia, departamento, altitud_msnm
             FROM clinico.distrito ORDER BY departamento, provincia, nombre""")).mappings().all()]


@router.get("/sintomas")
def sintomas(sesion: Session = Depends(sesion_clinica)) -> list[dict]:
    return [dict(f) for f in sesion.execute(text(
        "SELECT id_sintoma, nombre FROM clinico.sintoma ORDER BY id_sintoma")).mappings().all()]
