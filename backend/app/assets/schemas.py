from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.assets.models import AssetStatus, AssetType, validate_name


class AssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CreateAssetInput(AssetInput):
    name: str = Field(strict=True)
    type: AssetType
    status: AssetStatus

    @field_validator("name")
    @classmethod
    def check_name(cls, value: str) -> str:
        return validate_name(value)


class UpdateAssetInput(AssetInput):
    name: str | None = Field(default=None, strict=True)
    type: AssetType | None = None

    @model_validator(mode="after")
    def check_changes(self):
        if not self.model_fields_set:
            raise ValueError("Informe nome ou tipo do Asset.")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Os campos informados não podem ser nulos.")
        if "name" in self.model_fields_set:
            validate_name(self.name)
        return self


class PublicAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: AssetType
    status: AssetStatus
