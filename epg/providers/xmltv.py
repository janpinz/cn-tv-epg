"""XMLTV 数据源（默认：老张 EPG / 51zmt）。

一份 XML 里同时包含央视、卫视、部分付费频道，只需一次请求，
所以它是「批量频道」的首选源。

参考格式：
    <channel id="1"><display-name lang="zh">CCTV1</display-name></channel>
    <programme start="20261118001430 +0800" stop="..." channel="1">
        <title>人口-2026-46</title>
    </programme>
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from ..config import Settings, Source
from ..http import fetch_text
from ..models import Channel, Programme
from .base import Provider


def parse_xmltv_time(value: str, tz: ZoneInfo) -> datetime:
    """解析 '20261118001430 +0800'。"""
    value = value.strip()
    stamp = value.split()[0]
    if len(stamp) < 14:
        stamp = stamp.ljust(14, "0")
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=tz)


class XmltvProvider(Provider):
    """把整个 XMLTV 文件解析成 {频道显示名: [Programme]}。"""

    kind = "xmltv"

    def __init__(self, source: Source, settings: Settings) -> None:
        super().__init__(source, settings)
        self.tz = ZoneInfo(settings.timezone)
        self._index: dict[str, list[tuple[datetime, datetime | None, str, str | None]]] | None = None
        self._names: list[str] = []

    # ---- 内部 ----
    def _load(self) -> None:
        if self._index is not None:
            return
        if not self.source.url:
            raise ValueError(f"数据源 {self.source.id} 缺少 url")

        cache = self.settings.raw_dir() / self.source.id / "feed.xml"
        text = fetch_text(
            self.source.url,
            timeout=self.timeout,
            retries=self.retries,
            user_agent=self.user_agent,
            cache_path=cache,
        )

        root = ET.fromstring(text)
        id_to_name: dict[str, str] = {}
        for node in root.findall("channel"):
            channel_id = node.get("id") or ""
            display = node.find("display-name")
            id_to_name[channel_id] = (display.text or "").strip() if display is not None else channel_id
        self._names = sorted({n for n in id_to_name.values() if n})

        index: dict[str, list[tuple[datetime, datetime | None, str, str | None]]] = {}
        for node in root.findall("programme"):
            channel_id = node.get("channel") or ""
            name = id_to_name.get(channel_id)
            if not name:
                continue
            start_raw = node.get("start")
            if not start_raw:
                continue
            try:
                start = parse_xmltv_time(start_raw, self.tz)
            except ValueError:
                continue
            stop_raw = node.get("stop")
            stop: datetime | None = None
            if stop_raw:
                try:
                    stop = parse_xmltv_time(stop_raw, self.tz)
                except ValueError:
                    stop = None
            title_node = node.find("title")
            title = (title_node.text or "").strip() if title_node is not None else ""
            desc_node = node.find("desc")
            desc = (desc_node.text or "").strip() if desc_node is not None else None
            index.setdefault(name, []).append((start, stop, title, desc or None))

        for items in index.values():
            items.sort(key=lambda item: item[0])
        self._index = index

    def available_names(self) -> list[str]:
        """该源里所有频道名，供 `epg resolve` 使用。"""
        self._load()
        return self._names

    def fetch(self, channels: Iterable[Channel], dates: list[date]) -> dict[str, list[Programme]]:
        self._load()
        assert self._index is not None
        wanted = set(dates)
        result: dict[str, list[Programme]] = {}

        for channel in channels:
            items = self._index.get(channel.ref)
            if not items:
                continue
            programmes = [
                Programme(
                    channel_id=channel.id,
                    start=start,
                    stop=stop,
                    title=title,
                    desc=desc,
                )
                for start, stop, title, desc in items
                if start.date() in wanted
            ]
            if programmes:
                result[channel.id] = programmes
        return result
