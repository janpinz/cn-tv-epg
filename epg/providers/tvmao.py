"""电视猫（tvmao.com）数据源。

用途：央视 / 卫视之外的**地面频道**（江苏各市台、县台）几乎只有这里能拿到。
接口是普通 HTML 周表页，一天一页：

    https://www.tvmao.com/program/{code}-w{1..7}.html      # w1 = 周一

页面里只有「开始时间」，没有结束时间，因此用下一条的开始时间推算，
最后一条按 +60 分钟兜底。

页面结构：
    <ul id="pgrow">
      <li><div class="over_hide">
            <span class="am"> 00:55 </span>
            <span class="p_show"><a title="美好时代">美好时代</a></span>
          </div></li>
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from ..config import Settings, Source
from ..http import fetch_text
from ..models import Channel, Programme
from .base import Provider

_ITEM_RE = re.compile(
    r'<span class="(?:am|pm)"\s*>\s*(\d{1,3}):(\d{2})\s*</span>\s*'
    r'<span class="p_show">(.*?)</span>',
    re.DOTALL,
)
_TITLE_ATTR_RE = re.compile(r'title="([^"]*)"')
_AGG_RE = re.compile(
    r'class="tdchn">\s*<a\s+href="/program/([^"]+?)(?:-w\d+)?\.html"\s+title="([^"]+)"'
)


def _extract_title(block: str) -> str:
    attr = _TITLE_ATTR_RE.search(block)
    if attr:
        return attr.group(1).strip()
    text = re.sub(r"<[^>]+>", "", block)
    return text.replace("&nbsp;", " ").strip()


class TvmaoProvider(Provider):
    kind = "tvmao"

    def __init__(self, source: Source, settings: Settings) -> None:
        super().__init__(source, settings)
        self.tz = ZoneInfo(settings.timezone)
        self.base = (source.base or "https://www.tvmao.com").rstrip("/")

    # ---- 单日解析 ----
    def parse_day(self, html: str, channel_id: str, day: date) -> list[Programme]:
        marker = html.find('id="pgrow"')
        if marker < 0:
            return []
        end = html.find("</ul>", marker)
        block = html[marker : end if end > 0 else len(html)]

        slots: list[tuple[int, str]] = []
        for match in _ITEM_RE.finditer(block):
            hour = int(match.group(1))
            minute = int(match.group(2))
            title = _extract_title(match.group(3))
            if not title:
                continue
            slots.append((hour * 60 + minute, title))

        if not slots:
            return []

        # 去重（同一分钟重复出现时保留第一条）并按时间排序
        seen: set[int] = set()
        ordered: list[tuple[int, str]] = []
        for minutes, title in sorted(slots, key=lambda item: item[0]):
            if minutes in seen:
                continue
            seen.add(minutes)
            ordered.append((minutes, title))

        midnight = datetime.combine(day, dtime(0, 0), tzinfo=self.tz)
        programmes: list[Programme] = []
        for index, (minutes, title) in enumerate(ordered):
            start = midnight + timedelta(minutes=minutes)
            if index + 1 < len(ordered):
                stop = midnight + timedelta(minutes=ordered[index + 1][0])
            else:
                stop = start + timedelta(minutes=60)
            if stop <= start:
                stop = start + timedelta(minutes=60)
            programmes.append(
                Programme(channel_id=channel_id, start=start, stop=stop, title=title)
            )
        return programmes

    # ---- 对外接口 ----
    def page_url(self, code: str, day: date) -> str:
        return f"{self.base}/program/{code}-w{day.isoweekday()}.html"

    def fetch(self, channels: Iterable[Channel], dates: list[date]) -> dict[str, list[Programme]]:
        result: dict[str, list[Programme]] = {}
        for channel in channels:
            collected: list[Programme] = []
            for day in dates:
                url = self.page_url(channel.ref, day)
                cache = self.settings.raw_dir() / self.source.id / f"{channel.ref}-{day.isoformat()}.html"
                try:
                    html = fetch_text(
                        url,
                        timeout=self.timeout,
                        retries=self.retries,
                        user_agent=self.user_agent,
                        cache_path=cache,
                    )
                except Exception:
                    continue
                collected.extend(self.parse_day(html, channel.id, day))
                time.sleep(self.settings.delay)
            if collected:
                result[channel.id] = collected
        return result

    # ---- 频道发现：用于新增频道时查 code ----
    def discover(self, province_code: str = "320000", day: date | None = None) -> list[tuple[str, str]]:
        """按省份代码列出该省所有可用频道，返回 [(code, 名称)]。"""
        day = day or date.today()
        url = f"{self.base}/program/duration/{province_code}/w{day.isoweekday()}-h2.html"
        cache = self.settings.raw_dir() / self.source.id / f"discover-{province_code}-{day.isoformat()}.html"
        html = fetch_text(
            url,
            timeout=self.timeout,
            retries=self.retries,
            user_agent=self.user_agent,
            cache_path=cache,
        )
        found: dict[str, str] = {}
        for match in _AGG_RE.finditer(html):
            code = match.group(1)
            name = match.group(2)
            found.setdefault(code, name)
        return sorted(found.items(), key=lambda item: item[1])
