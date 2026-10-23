def test_salud_reporta_cada_conexion(cliente):
    r = cliente.get("/api/salud")
    assert r.status_code == 200
    datos = r.json()
    assert datos["bd_clinica"] == datos["bd_generacion"] == datos["bd_admin"] == "ok"
    assert "chromadb" in datos
