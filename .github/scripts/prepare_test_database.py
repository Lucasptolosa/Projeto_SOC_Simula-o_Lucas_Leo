import json
import os
from pathlib import Path
import re
import secrets
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LOGGING_PROFILE = {
    "log_error_verbosity": "terse",
    "log_min_error_statement": "panic",
    "log_statement": "none",
    "log_parameter_max_length": "0",
    "log_parameter_max_length_on_error": "0",
    "log_min_duration_statement": "-1",
    "log_min_duration_sample": "-1",
    "log_transaction_sample_rate": "0",
}


def docker(*arguments, input=None):
    return subprocess.run(
        ["docker", *arguments], input=input, text=True, capture_output=True,
        check=True, timeout=30,
    ).stdout


def validated_service():
    # Somente runner hospedado
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise ValueError("Preparação permitida somente no runner hospedado.")
    container = os.environ.get("CI_POSTGRES_CONTAINER", "")
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise ValueError("Identificador do serviço inválido.")
    settings = {"DB_HOST": "127.0.0.1", "DB_PORT": "5432", "DB_NAME": "mini_soc_test", "DB_USER": "mini_soc_app"}
    if any(os.environ.get(key) != value for key, value in settings.items()):
        raise ValueError("Configuração fora do serviço de testes.")
    service = json.loads(docker("inspect", container))[0]
    bindings = service["NetworkSettings"]["Ports"]["5432/tcp"]
    if service["Config"]["Image"] != "postgres:17-bookworm" or not service["State"]["Running"]:
        raise ValueError("Imagem/estado do serviço inválido.")
    if bindings != [{"HostIp": "127.0.0.1", "HostPort": "5432"}]:
        raise ValueError("Serviço deve estar restrito ao loopback.")
    return container, settings


def prepare():
    container, settings = validated_service()
    target = ROOT / "backend" / ".env.test"
    if target.exists():
        raise ValueError("O dotenv de testes já existe.")

    password = secrets.token_hex(32)
    print(f"::add-mask::{password}", flush=True)
    sql = f"""
        SET password_encryption = 'scram-sha-256';
        CREATE ROLE mini_soc_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS PASSWORD '{password}';
        ALTER DATABASE mini_soc_test OWNER TO mini_soc_app;
        REVOKE ALL ON DATABASE mini_soc_test FROM PUBLIC;
    """
    # Somente banco descartável
    sql += "".join(
        f"ALTER DATABASE mini_soc_test SET {name} = '{value}';\n"
        for name, value in LOGGING_PROFILE.items()
    )
    psql = ["exec", "-i", "--user", "postgres", container, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "mini_soc_test"]
    database = docker(*psql, "-tAc", "SELECT current_database()")
    if database.strip() != "mini_soc_test":
        raise ValueError("Banco real incorreto.")
    docker(*psql, input=sql)

    # Fecha bootstrap TCP
    hba = (
        "local all postgres trust\n"
        "local all all scram-sha-256\n"
        "host all postgres all reject\n"
        "host mini_soc_test mini_soc_app all scram-sha-256\n"
        "host all all all reject\n"
    )
    docker("exec", "-i", "--user", "postgres", container, "sh", "-c", 'cat > "$PGDATA/pg_hba.conf"', input=hba)
    docker(*psql, "-tAc", "SELECT pg_reload_conf()")
    settings["DB_PASSWORD"] = password
    with target.open("x", encoding="utf-8") as stream:
        target.chmod(0o600)
        stream.write("".join(f"{key}={value}\n" for key, value in settings.items()))
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
        stream.write(f"DB_PASSWORD={password}\n")
    print("Role restrita e autenticação SCRAM preparadas em mini_soc_test.")


if __name__ == "__main__":
    try:
        prepare()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        raise SystemExit("Falha na preparação isolada; nenhuma credencial foi exibida.") from None
