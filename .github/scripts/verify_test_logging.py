import os
import re
import secrets
import subprocess
import time

import psycopg

from prepare_test_database import LOGGING_PROFILE, docker, validated_service


class LoggingCheckError(ValueError):
    pass


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
            "-v", "VERBOSITY=sqlstate", "-U", "postgres", "-d", "mini_soc_test"]
    print("Serviço descartável validado.", flush=True)
    if docker(*psql, "-tAc", "SELECT current_database()").strip() != "mini_soc_test":
        raise LoggingCheckError("Banco real incorreto.")
    # Controle positivo isolado
    baseline = secrets.token_hex(24)
    print(f"::add-mask::{baseline}", flush=True)
    sql = f"""
        BEGIN;
        SET LOCAL log_error_verbosity = 'default';
        CREATE TEMP TABLE ci_log_probe(value text CHECK (value = ''));
        INSERT INTO ci_log_probe(value) VALUES ('{baseline}');
    """
    result = subprocess.run(["docker", *psql], input=sql, capture_output=True, text=True, timeout=30)
    state = re.search(r"(?:ERROR|FATAL):\s+([0-9A-Z]{5})(?=\s|$)", result.stderr)
    if result.returncode == 0 or state is None or state[1] != "23514":
        raise LoggingCheckError(f"Controle SQL inesperado: retorno={result.returncode}, SQLSTATE={state[1] if state else 'ausente'}.")
    if not marker_logged(container, baseline):
        raise LoggingCheckError("Controle positivo ausente no log real.")
    print("DEFAULT: marcador sintético encontrado no log do servidor.")

    # Perfil real aplicação
    marker = secrets.token_hex(24)
    print(f"::add-mask::{marker}", flush=True)
    with psycopg.connect(
        host=settings["DB_HOST"], port=settings["DB_PORT"], dbname="mini_soc_test",
        user=settings["DB_USER"], password=os.environ["DB_PASSWORD"], connect_timeout=5,
    ) as connection:
        if connection.execute("SELECT current_database(), current_user").fetchone() != ("mini_soc_test", "mini_soc_app"):
            raise LoggingCheckError("Banco/role fora do ambiente descartável.")
        profile = dict(connection.execute(
            "SELECT name,setting FROM pg_settings WHERE name = ANY(%s)",
            (list(LOGGING_PROFILE),),
        ).fetchall())
        if profile != LOGGING_PROFILE:
            raise LoggingCheckError("Perfil de logging inesperado.")
        connection.execute("CREATE TEMP TABLE ci_log_probe(value text CHECK (value = ''))")
        try:
            connection.execute("INSERT INTO ci_log_probe(value) VALUES (%s)", (marker,))
        except psycopg.errors.CheckViolation:
            connection.rollback()
        else:
            raise LoggingCheckError("Falha esperada não ocorreu.")
    if marker_logged(container, marker):
        raise LoggingCheckError("Perfil restrito expôs o marcador.")
    print("TERSE: violação CHECK confirmada sem marcador no log real; parâmetros e statements restritos.")


if __name__ == "__main__":
    try:
        verify()
    except LoggingCheckError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit(f"Verificação de logging reprovada: {type(error).__name__}; conteúdo omitido.") from None
