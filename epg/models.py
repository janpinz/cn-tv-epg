"""数据模型：频道、节目、节目单。

所有时间统一为带时区的 aware datetime（默认 Asia/Shanghai），
避免在不同机器 / CI 环境下出现时区漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo


@dataclass(frozen=True)
class Channel:
    """一个频道。"""

    id: str
    name: str
    group: str  # cctv / satellite / jiangsu
    source: str  # 数据源 id
    ref: str  # 数据源内的原始名称或编号
    logo: str | None = None
    # 别名：用于和外部 m3u 播放列表里的 tvg-id / 频道名对齐
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Group:
    """频道分组，用于展示顺序与网页分栏。"""

    id: str
    name: str
    channels: tuple[Channel, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Programme:
    """一档节目。stop 可能为 None（表示未知，导出时按 +1 小时推算）。"""

    channel_id: str
    start: datetime
    stop: datetime | None
    title: str
    desc: str | None = None
    category: str | None = None

    @property
    def date_key(self) -> str:
        """归属日期（按开始时间所在的本地日期）。"""
        return self.start.strftime("%Y-%m-%d")

    @property
    def minutes(self) -> int:
        if self.stop is None:
            return 0
        return max(0, int((self.stop - self.start).total_seconds() // 60))


@dataclass
class Guide:
    """完整节目单：分组 + 每个频道的节目列表 + 生成元信息。"""

    groups: tuple[Group, ...]
    programmes: dict[str, list[Programme]]
    generated_at: datetime
    timezone: tzinfo

    @property
    def channels(self) -> tuple[Channel, ...]:
        return tuple(ch for g in self.groups for ch in g.channels)

    @property
    def dates(self) -> list[str]:
        keys: set[str] = set()
        for items in self.programmes.values():
            for p in items:
                keys.add(p.date_key)
        return sorted(keys)

    def count(self, channel_id: str) -> int:
        return len(self.programmes.get(channel_id, ()))

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.programmes.values())


def fmt_xmltv_time(dt: datetime) -> str:
    """XMLTV 时间格式：20261118001430 +0800"""
    offset = dt.strftime("%z") or "+0800"
    return f"{dt.strftime('%Y%m%d%H%M%S')} {offset}"
