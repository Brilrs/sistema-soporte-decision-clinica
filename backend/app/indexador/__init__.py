"""Pipeline de indexación de las guías clínicas (OE2, sección 4.1): extracción con
pdfplumber, transcripciones de tablas críticas, mapa de modificaciones de la
RM 429-2024/MINSA, fragmentación, embeddings y escritura en PostgreSQL y ChromaDB.
Se ejecuta en el contenedor jobs con el usuario de base de datos cdss_indexador."""
