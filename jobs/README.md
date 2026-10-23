# Jobs (procesos fuera de línea)

Contenedor que agrupa los procesos que no forman parte de la atención en tiempo real.
Se implementa en el **Sprint 2** y siguientes:

- `indexador`: pipeline de indexación de guías (extracción, fragmentación 500/800/80, MeSH/DeCS, embeddings bge-m3, ChromaDB y BM25).
- `evaluacion`: métricas RAGAS y CUE del OE3 sobre los casos clínicos de prueba.
- `respaldo`: copia diaria del índice de ChromaDB hacia Azure Blob Storage.
