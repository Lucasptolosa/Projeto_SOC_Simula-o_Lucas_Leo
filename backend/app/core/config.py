
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    db_host: str
    db_port: int = Field(ge=1, le=65535)
    db_name: str
    db_user: str
    db_password: SecretStr
    auth_origin: str = "https://localhost"
    auth_cookie_secure: bool = True
    auth_session_seconds: int = Field(default=28800, ge=1, le=86400)

    @model_validator(mode="after")
    def validate_auth_settings(self):
        origin = urlsplit(self.auth_origin)
        if (
            origin.scheme not in {"https", "http"}
            or not origin.hostname
            or (origin.port is not None and origin.port < 1)
            or origin.username is not None
            or origin.password is not None
            or origin.path not in {"", "/"}
            or origin.query or origin.fragment
        ):
            raise ValueError("AUTH_ORIGIN deve conter somente esquema, host e porta.")
        if not self.auth_cookie_secure and (
            origin.scheme != "http" or origin.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Cookie sem Secure permitido somente em HTTP loopback.")
        if self.auth_cookie_secure and origin.scheme != "https":
            raise ValueError("Cookie Secure exige origem HTTPS.")
        self.auth_origin = self.auth_origin.rstrip("/")
        return self

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )
