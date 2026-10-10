import logging
from dataclasses import dataclass
from collections.abc import Callable

logger = logging.getLogger("jarvis.events")


@dataclass(frozen=True)
class Event:
    name: str
    state: str
    detail: str = ""


class EventBus:
    def __init__(self):
        self._listeners: list[Callable[[Event], None]] = []

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def emit(self, event: Event) -> None:
        logger.info("%s %s", event.name, event.state)
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                logger.warning("event listener failed")
