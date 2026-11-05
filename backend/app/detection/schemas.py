from typing import Literal

from pydantic import BaseModel, ConfigDict


RuleStatus = Literal["ACTIVE", "INACTIVE"]


class UpdateRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    status: RuleStatus


class PublicRule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: RuleStatus
    severity: Literal["HIGH", "MEDIUM"]
