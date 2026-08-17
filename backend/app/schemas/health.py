from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    status: Literal["正常", "不可用"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["正常", "不可用"]
    components: dict[str, ComponentHealth] = Field(default_factory=dict)
