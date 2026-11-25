"""docker simulado para las pruebas de deploy/ (parte L). Anota cada llamada en FAKE_LOG y responde lo
mínimo: contenedores sanos, un pg_dump falso, pg_restore que lee la entrada y conteos de psql. Las
variables FAKE_* provocan fallas."""
import json
import os
import sys


def main(args: list[str]) -> int:
    texto = " ".join(args)
    entrada = b""
    if "pg_restore" in texto:
        entrada = sys.stdin.buffer.read()
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"programa": "docker", "argv": args, "bytes_entrada": len(entrada)}) + "\n")
    if args[:1] == ["inspect"]:
        print("healthy")
        return 0
    if args[:1] != ["compose"]:
        return 0
    if "ps" in args and "-q" in args:
        print(f"id-{args[-1]}")
        return 0
    if "exec" in args:
        if "pg_dump" in texto:
            if not os.environ.get("FAKE_PGDUMP_VACIO"):
                sys.stdout.buffer.write(b"PGDMP-falso-" + os.urandom(64))
            return 0
        if "pg_restore" in texto and "--list" in args:
            return 1 if os.environ.get("FAKE_PGRESTORE_FALLA") or not entrada else 0
        if "psql" in texto:
            base, sql = args[-2], args[-1]
            if "information_schema.tables" in sql:
                print(os.environ.get("FAKE_TABLAS_PRUEBA", "40") if base == "cdss_prueba_restauracion" else "40")
            else:
                print("7")
            return 0
        return 0
    if "run" in args:
        if "comparar" in args and os.environ.get("FAKE_COMPARAR_FALLA"):
            return 1
        if "crear" in args and os.environ.get("FAKE_CREAR_FALLA"):
            return 1
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
