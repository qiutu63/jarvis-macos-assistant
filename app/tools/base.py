from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from app.permissions.policy import Risk


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[BaseModel]
    handler: Callable[..., Awaitable[object]]
    risk: Risk = Risk.CONFIRM
    timeout: float | None = None
    parameters_schema: dict | None = None

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                     "parameters": self.parameters_schema or self.arguments.model_json_schema()}}
