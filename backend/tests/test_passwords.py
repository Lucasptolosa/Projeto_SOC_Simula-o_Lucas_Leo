import base64
import secrets

import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type

from app.core.passwords import hash_password, validate_password_hash


def test_argon2id_salt_individual():
    # Arrange
    password = secrets.token_urlsafe(24)

    # Act
    first = hash_password(password)
    second = hash_password(password)
    salt = base64.b64decode(first.split("$")[4] + "==")

    # Assert
    assert first != second
    assert len(salt) >= 16
    assert extract_parameters(first).type is Type.ID
    assert PasswordHasher().verify(first, password)
    assert validate_password_hash(first) == first


@pytest.mark.parametrize("password", ["", " ", "\t\n", None])
def test_senha_vazia_rejeitada(password):
    # Arrange
    invalid_password = password

    # Act
    with pytest.raises(ValueError) as error:
        hash_password(invalid_password)

    # Assert
    assert str(error.value) == "A senha deve ser não vazia."


@pytest.mark.parametrize("password", ["x", "á🔒", " x "])
def test_senha_preservada_sem_truncamento(password):
    # Arrange
    verifier = PasswordHasher()

    # Act
    encoded = hash_password(password)

    # Assert
    assert verifier.verify(encoded, password)


@pytest.mark.parametrize("kind", ["plaintext", "salt_curto", "salt_limite", "argon2i", "malformado", "base64"])
def test_hash_invalido_rejeitado(kind):
    # Arrange
    password = secrets.token_urlsafe(24)
    values = {
        "plaintext": password,
        "salt_curto": PasswordHasher(salt_len=8).hash(password),
        "salt_limite": PasswordHasher(salt_len=15).hash(password),
        "argon2i": PasswordHasher(type=Type.I).hash(password),
        "malformado": "$argon2id$v=19$m=1,t=0,p=0$" + "a" * 22 + "$" + "b" * 43,
        "base64": "$argon2id$v=19$m=65536,t=3,p=4$" + "a" * 23 + "$" + "b" * 43,
    }

    # Act
    with pytest.raises(ValueError) as error:
        validate_password_hash(values[kind])

    # Assert
    assert str(error.value) == "Hash Argon2id inválido."
