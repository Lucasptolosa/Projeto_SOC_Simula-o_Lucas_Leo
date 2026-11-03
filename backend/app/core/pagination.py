from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


Item = TypeVar("Item")


class PaginationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=20, ge=1, le=100)


class Page(BaseModel, Generic[Item]):
    items: list[Item]
    total: int = Field(ge=0)
    page: int
    page_size: int
