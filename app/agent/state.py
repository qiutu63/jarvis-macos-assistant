from enum import StrEnum


class State(StrEnum):
    WAITING = "Waiting"
    LISTENING = "Listening"
    THINKING = "Thinking"
    PLANNING = "Planning"
    EXECUTING = "Executing"
    OBSERVING = "Observing"
    COMPLETED = "Completed"
    ERROR = "Error"
