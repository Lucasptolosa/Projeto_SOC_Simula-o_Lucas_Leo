import secrets
import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from getpass import GetPassWarning
import warnings

from app.users import create_admin
from app.users.models import User


def prepare_terminal(monkeypatch, password, confirmation=None):
    monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "operador")
    answers = iter([password, password if confirmation is None else confirmation])
    monkeypatch.setattr(create_admin, "getpass", lambda _: next(answers))


def test_comando_cria_admin(users_db, monkeypatch, capsys):
    # Arrange
    factory, _ = users_db
    password = secrets.token_urlsafe(24)
    prepare_terminal(monkeypatch, password)
    monkeypatch.setattr(create_admin, "get_session_factory", lambda: factory)

    # Act
    result = create_admin.main([])
    output = capsys.readouterr()

    # Assert
    assert result == 0
    assert password not in output.out + output.err
    with factory() as session:
        assert session.scalar(select(User.username)) == "operador"


@pytest.mark.parametrize("mode", ["argumento", "sem_terminal", "confirmacao"])
def test_comando_recusa_entrada_insegura(monkeypatch, capsys, mode):
    # Arrange
    password = secrets.token_urlsafe(24)
    prepare_terminal(monkeypatch, password, "diferente")
    args = ["--password", password] if mode == "argumento" else []
    if mode == "sem_terminal":
        monkeypatch.setattr(create_admin.sys.stdin, "isatty", lambda: False)

    # Act
    result = create_admin.main(args)
    output = capsys.readouterr()

    # Assert
    assert result == 2
    assert password not in output.out + output.err


def test_comando_erro_sem_segredos(monkeypatch, capsys):
    # Arrange
    password = secrets.token_urlsafe(24)
    prepare_terminal(monkeypatch, password)
    def fail_factory():
        raise SQLAlchemyError(password)
    monkeypatch.setattr(create_admin, "get_session_factory", fail_factory)

    # Act
    result = create_admin.main([])
    output = capsys.readouterr()

    # Assert
    assert result == 1
    assert password not in output.out + output.err


def test_comando_cancelado(monkeypatch, capsys):
    # Arrange
    prepare_terminal(monkeypatch, secrets.token_urlsafe(24))
    def cancelled(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(create_admin, "getpass", cancelled)

    # Act
    result = create_admin.main([])
    output = capsys.readouterr()

    # Assert
    assert result == 1
    assert "Operação cancelada" in output.err


def test_comando_nao_repete_bootstrap(users_db, monkeypatch, capsys):
    # Arrange
    factory, _ = users_db
    password = secrets.token_urlsafe(24)
    prepare_terminal(monkeypatch, password)
    monkeypatch.setattr(create_admin, "get_session_factory", lambda: factory)
    assert create_admin.main([]) == 0
    prepare_terminal(monkeypatch, password)

    # Act
    result = create_admin.main([])
    output = capsys.readouterr()

    # Assert
    assert result == 1
    assert "já inicializada" in output.err
    assert password not in output.out + output.err


def test_comando_bloqueia_fallback_visivel(monkeypatch, capsys):
    # Arrange
    prepare_terminal(monkeypatch, secrets.token_urlsafe(24))
    def unsafe_prompt(_):
        warnings.warn("Sem terminal seguro", GetPassWarning)
        pytest.fail("Senha não deve ser lida")
    monkeypatch.setattr(create_admin, "getpass", unsafe_prompt)

    # Act
    result = create_admin.main([])
    output = capsys.readouterr()

    # Assert
    assert result == 1
    assert "Operação cancelada" in output.err


def test_comando_real_recusa_pipe():
    # Arrange
    password = secrets.token_urlsafe(24)

    # Act
    result = subprocess.run(
        [sys.executable, "-m", "app.users.create_admin"],
        input=password, text=True, capture_output=True, timeout=10,
    )

    # Assert
    assert result.returncode == 2
    assert "terminal interativo" in result.stderr
    assert password not in result.stdout + result.stderr
