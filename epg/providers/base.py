"""数据源基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from ..config import Settings, Source
from ..models import Channel, Programme


class Provider(ABC):
    """所有数据源的统一接口。"""

    kind: str = ""

    def __init__(self, source: Source, settings: Settings) -> None:
        self.source = source
        self.settings = settings

    @abstractmethod
    def fetch(self, channels: Iterable[Channel], dates: list[date]) -> dict[str, list[Programme]]:
        """返回 {channel.id: [Programme, ...]}。

        某些频道在该源无数据时，可以不返回该 key（上层会记为缺数据）。
        """

    # ---- 供子类复用的小工具 ----
    @property
    def timeout(self) -> int:
        return self.settings.timeout

    @property
    def retries(self) -> int:
        return self.settings.retries

    @property
    def user_agent(self) -> str:
        return self.settings.user_agent
