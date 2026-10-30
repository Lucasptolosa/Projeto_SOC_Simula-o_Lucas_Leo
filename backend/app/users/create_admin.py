import sys
import warnings
from getpass import GetPassWarning, getpass

from argon2.exceptions import HashingError
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_session_factory
from app.users.bootstrap import BootstrapError, create_initial_admin


def main(argv: list[str] | None = None) -> int:
    if (sys.argv[1:] if argv is None else argv):
        print("O comando não aceita argumentos.", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("Use um terminal interativo para informar a senha.", file=sys.stderr)
        return 2

    try:
        username = input("Nome do Administrator: ")
        # Impede fallback visível
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Senha: ")
            confirmation = getpass("Confirme a senha: ")
        if password != confirmation:
            print("As senhas não coincidem.", file=sys.stderr)
            return 2

        factory = get_session_factory()
        with factory.begin() as session:
            create_initial_admin(session, username, password)
    except BootstrapError:
        print("Instalação já inicializada; nenhum usuário foi alterado.", file=sys.stderr)
        return 1
    except (ValueError, SQLAlchemyError, HashingError):
        print("Falha na criação. Verifique os dados, a configuração e a migration.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print("Operação cancelada; nenhuma conta foi criada.", file=sys.stderr)
        return 1

    print("Administrator inicial criado com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
