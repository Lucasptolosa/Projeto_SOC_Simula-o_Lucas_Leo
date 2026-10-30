import re
from base64 import b64decode, b64encode
from binascii import Error as Base64Error

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


ARGON2ID_PATTERN = (
    r"\$argon2id\$v=19\$m=[0-9]+,t=[0-9]+,p=[0-9]+"
    r"\$[A-Za-z0-9+/]{22,}\$[A-Za-z0-9+/]{22,}"
)

# Salt individual aleatório
_hasher = PasswordHasher(
    type=Type.ID, salt_len=16, hash_len=32,
    time_cost=3, memory_cost=65536, parallelism=4,
)


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password.strip():
        raise ValueError("A senha deve ser não vazia.")
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        validate_password_hash(encoded)
        return _hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError, ValueError):
        return False


def validate_password_hash(value: str) -> str:
    try:
        if not isinstance(value, str) or re.fullmatch(ARGON2ID_PATTERN, value) is None:
            raise InvalidHashError
        parameters = extract_parameters(value)
        for part in value.split("$")[4:]:
            decoded = b64decode(part + "=" * (-len(part) % 4), validate=True)
            if b64encode(decoded).decode("ascii").rstrip("=") != part:
                raise InvalidHashError
        if (
            parameters.type is not Type.ID
            or parameters.version != 19
            or parameters.salt_len < 16
            or parameters.hash_len < 16
            or parameters.parallelism < 1
            or parameters.time_cost < 1
            or parameters.memory_cost < 8 * parameters.parallelism
        ):
            raise InvalidHashError
    except (InvalidHashError, ValueError, Base64Error):
        raise ValueError("Hash Argon2id inválido.") from None
    return value
