from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.assets.models import Asset, AssetStatus, AssetType
from app.assets.schemas import CreateAssetInput, PublicAsset, UpdateAssetInput


@pytest.mark.parametrize("kind", list(AssetType))
@pytest.mark.parametrize("status", list(AssetStatus))
def test_create_contract_accepts_approved_values(kind, status):
    # Arrange
    data = {"name": " Servidor São Paulo ", "type": kind.value, "status": status.value}
    # Act
    payload = CreateAssetInput.model_validate(data)
    # Assert
    assert payload.name == data["name"]
    assert payload.type is kind
    assert payload.status is status


@pytest.mark.parametrize("changes", [
    {"name": ""}, {"name": " \t\n"}, {"name": "\u2003"}, {"name": None},
    {"name": 42}, {"type": "server"}, {"type": "INVALID"}, {"type": None},
    {"status": "active"}, {"status": "INVALID"}, {"status": None},
    {"id": str(uuid4())}, {"unknown": "value"},
])
def test_create_contract_rejects_invalid_values(changes):
    # Arrange
    data = {"name": "servidor", "type": "SERVER", "status": "ACTIVE"} | changes
    # Act
    with pytest.raises(ValidationError) as error:
        CreateAssetInput.model_validate(data)
    # Assert
    assert error.value.error_count() > 0


@pytest.mark.parametrize("field", ["name", "type", "status"])
def test_create_requires_all_fields(field):
    # Arrange
    data = {"name": "servidor", "type": "SERVER", "status": "ACTIVE"}
    del data[field]
    # Act
    with pytest.raises(ValidationError) as error:
        CreateAssetInput.model_validate(data)
    # Assert
    assert any(item["loc"] == (field,) for item in error.value.errors())


@pytest.mark.parametrize("data", [{"name": "novo"}, {"type": "APPLICATION"}, {"name": "novo", "type": "WORKSTATION"}])
def test_update_contains_only_requested_fields(data):
    # Arrange
    original = dict(data)
    # Act
    payload = UpdateAssetInput.model_validate(data)
    # Assert
    assert payload.model_dump(exclude_unset=True) == original
    assert data == original


@pytest.mark.parametrize("data", [
    {}, {"name": None}, {"type": None}, {"name": ""}, {"name": " \t"},
    {"name": 5}, {"type": "INVALID"}, {"status": "ACTIVE"}, {"id": str(uuid4())},
    {"name": "valid", "type": None},
])
def test_update_rejects_empty_null_or_protected_fields(data):
    # Arrange
    original = dict(data)
    # Act
    with pytest.raises(ValidationError):
        UpdateAssetInput.model_validate(data)
    # Assert
    assert data == original


@pytest.mark.parametrize("field,value", [("name", ""), ("name", "\t"), ("name", None), ("type", "ROOT"), ("status", "REMOVED")])
def test_orm_validation_rejects_invalid_values(field, value):
    # Arrange
    data = {"name": "servidor", "type": "SERVER", "status": "ACTIVE"}
    data[field] = value
    # Act
    with pytest.raises(ValueError):
        Asset(**data)
    # Assert
    assert data[field] == value


def test_name_is_not_unique_in_metadata():
    # Arrange
    column = Asset.__table__.c.name
    # Act
    unique_names = [constraint for constraint in Asset.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"]
    # Assert
    assert not column.unique
    assert unique_names == []


def test_public_contract_exposes_only_asset_fields():
    # Arrange
    asset = Asset(id=uuid4(), name="servidor", type="SERVER", status="INACTIVE")
    # Act
    result = PublicAsset.model_validate(asset).model_dump(mode="json")
    # Assert
    assert set(result) == {"id", "name", "type", "status"}
    assert result["id"] == str(asset.id)
    assert result["status"] == "INACTIVE"
