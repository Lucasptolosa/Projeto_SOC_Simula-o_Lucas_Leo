import os
import secrets
import subprocess
import time

import psycopg

from prepare_test_database import LOGGING_PROFILE, docker, validated_service


def server_logs(container):
    result = subprocess.run(
        ["docker", "logs", container], capture_output=True, text=True,
        check=True, timeout=30,
    )
    return result.stdout + result.stderr


def marker_logged(container, marker):
    for _ in range(10):
        if marker in server_logs(container):
            return True
        time.sleep(0.1)
    return False


def verify():
    container, settings = validated_service()
    psql = ["exec", "-i", "--user", "postgres", container, "psql", "-X", "-v", "ON_ERROR_STOP=1",
            "-U", "postgres", "-d", "mini_soc_test"]
    if docker(*psql, "-tAc", "SELECT current_database()").strip() != "mini_soc_test":
        raise ValueError("Banco real incorreto.")
    # Controle positivo isolado
    baseline = secrets.token_hex(24)
    sql = f"""
        BEGIN;
        SET LOCAL log_error_verbosity = 'default';
        CREATE TEMP TABLE ci_log_probe(value text CHECK (value = ''));
        INSERT INTO ci_log_probe(value) VALUES ('{baseline}');
    """
    result = subprocess.run(["docker", *psql], input=sql, capture_output=True, text=True, timeout=30)
    if result.returncode != 3 or not marker_logged(container, baseline):
        raise ValueError("Controle positivo de logging não comprovado.")
    print("DEFAULT: marcador sintético encontrado no log do servidor.")

    # Perfil real aplicação
    marker = secrets.token_hex(24)
    with psycopg.connect(
        host=settings["DB_HOST"], port=settings["DB_PORT"], dbname="mini_soc_test",
        user=settings["DB_USER"], password=os.environ["DB_PASSWORD"], connect_timeout=5,
    ) as connection:
        if connection.execute("SELECT current_database(), current_user").fetchone() != ("mini_soc_test", "mini_soc_app"):
            raise ValueError("Banco/role fora do ambiente descartável.")
        profile = dict(connection.execute(
            "SELECT name,setting FROM pg_settings WHERE name = ANY(%s)",
            (list(LOGGING_PROFILE),),
        ).fetchall())
        if profile != LOGGING_PROFILE:
            raise ValueError("Perfil de logging inesperado.")
        connection.execute("CREATE TEMP TABLE ci_log_probe(value text CHECK (value = ''))")
        try:
            connection.execute("INSERT INTO ci_log_probe(value) VALUES (%s)", (marker,))
        except psycopg.errors.CheckViolation:
            connection.rollback()
        else:
            raise ValueError("Falha esperada não ocorreu.")
    if marker_logged(container, marker):
        raise ValueError("Perfil restrito expôs o marcador.")
    print("TERSE: violação CHECK confirmada sem marcador no log real; parâmetros e statements restritos.")


if __name__ == "__main__":
    try:
        verify()
    except Exception as error:
        raise SystemExit(f"Verificação de logging reprovada: {type(error).__name__}; conteúdo omitido.") from None
