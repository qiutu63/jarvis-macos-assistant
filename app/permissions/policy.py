from enum import StrEnum


class Risk(StrEnum):
    SAFE = "SAFE"
    CONFIRM = "CONFIRM"
    BLOCKED = "BLOCKED"
