import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RepairDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: uuid.UUID
    note: str = Field(min_length=1, max_length=3000)
    revision: str = Field(min_length=1, max_length=64)


class DraftFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["applied", "rejected", "helpful", "not_helpful"]
    reason: Literal["accurate", "missing_facts", "wrong_meaning", "other"] | None = None
