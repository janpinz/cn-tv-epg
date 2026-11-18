"""按频道名查询的 JSON 数据源（默认：51zmt 的 diyp 接口）。

有些频道不在整包 XMLTV 里（例如中学生、东方财经、生活时尚），
但它们能通过「按名字查一天」的接口拿到，格式是 JSON：

    GET http://epg.51zmt.top:8000/api/diyp/?ch=东方财经&date=2026-11-18

    {"channel_name": "东方财经", "date": "2026-11-18",
     "epg_data": [{"start": "00:05", "end": "01:00", "title": "纪录片 --免费使用"}]}

标题里的「--免费使用」尾巴由 normalize 统一清掉。
频道不存在时接口返回 channel_name = "未提供"，此时整条丢弃。
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..config import Settings, Source
from ..http import fetch_text
from ..models import Channel, Programme
from .base import Provider

_NOT_FOUND = "未提供"
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _minutes(value: str) -> int | None:
    match = _CLOCK_RE.match((value or "").strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


class DiypProvider(Provider):
    kind = "diyp"

    def __init__(self, source: Source, settings: Settings) -> None:
        super().__init__(source, settings)
        self.tz = ZoneInfo(settings.timezone)
        self.base = (source.base or "http://epg.51zmt.top:8000/api/diyp/").rstrip("/")

    def api_url(self, name: str, day: date) -> str:
        query = urlencode({"ch": name, "date": day.isoformat()})
        return f"{self.base}/?{query}"

    def parse_payload(self, text: str, channel_id: str, day: date) -> list[Programme]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict):
            return []
        if (payload.get("channel_name") or "").strip() == _NOT_FOUND:
            return []

        midnight = datetime.combine(day, dtime(0, 0), tzinfo=self.tz)
        programmes: list[Programme] = []
        for item in payload.get("epg_data") or []:
            start_min = _minutes(str(item.get("start", "")))
            if start_min is None:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            start = midnight + timedelta(minutes=start_min)
            end_min = _minutes(str(item.get("end", "")))
            stop: datetime | None = None
            if end_min is not None:
                stop = midnight + timedelta(minutes=end_min)
                if stop <= start:  # 跨零点
                    stop += timedelta(days=1)
            programmes.append(
                Programme(channel_id=channel_id, start=start, stop=stop, title=title)
            )
        return programmes

    def fetch(self, channels: Iterable[Channel], dates: list[date]) -> dict[str, list[Programme]]:
        result: dict[str, list[Programme]] = {}
        for channel in channels:
            collected: list[Programme] = []
            for day in dates:
                url = self.api_url(channel.ref, day)
                cache = self.settings.raw_dir() / self.source.id / f"{channel.id}-{day.isoformat()}.json"
                try:
                    text = fetch_text(
                        url,
                        timeout=self.timeout,
                        retries=self.retries,
                        user_agent=self.user_agent,
                        cache_path=cache,
                    )
                except Exception:
                    continue
                collected.extend(self.parse_payload(text, channel.id, day))
                time.sleep(self.settings.delay)
            if collected:
                result[channel.id] = collected
        return result
