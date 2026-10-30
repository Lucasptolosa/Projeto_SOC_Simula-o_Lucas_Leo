from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator

from app.users.models import UserRole, UserStatus


class UserInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("username", check_fields=False)
    @classmethod
    def nonempty_username(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Username não pode ser vazio.")
        return value


class CreateUserInput(UserInput):
    username: str
    role: UserRole
    password: SecretStr

    @field_validator("password")
    @classmethod
    def nonempty_password(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("Senha não pode ser vazia.")
        return value


class UpdateUserInput(UserInput):
    username: str | None = None
    role: UserRole | None = None

    @model_validator(mode="after")
    def explicit_changes(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Informe username ou papel válido.")
        return self


class PublicUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    username: str
    role: UserRole
    status: UserStatus
