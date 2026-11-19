"""Respaldo de la base de conocimiento vectorial (Sprint 3, parte K).

Exporta la colección de ChromaDB por su API (ids, vectores, textos y metadatos, más los
metadatos de la colección) y las guías cargadas desde M11, con un manifiesto de SHA-256; restaura
en una colección vacía y comprueba la colección contra PostgreSQL. PostgreSQL no entra: en Azure
tiene su propio respaldo (docs/respaldo.md). Uso: python -m app.respaldo --help."""
