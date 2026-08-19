from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Notification:
    timestamp: datetime
    severity: str
    category: str
    message: str
    acknowledged: bool = False


class NotificationProvider(ABC):
    @abstractmethod
    async def send(self, notification: Notification) -> None: ...


class LocalDashboardNotifications(NotificationProvider):
    def __init__(self, capacity: int = 500) -> None:
        self.capacity = capacity
        self._items: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self._items.append(notification)
        self._items = self._items[-self.capacity :]

    def latest(self, limit: int = 50) -> tuple[Notification, ...]:
        return tuple(reversed(self._items[-limit:]))
