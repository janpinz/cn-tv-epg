"""把外部 M3U 播放列表和本节目单的频道 id 对齐。

播放器是按 `tvg-id` 去 EPG 里找频道的，两边的 id 写法必须一致。
现实里各家 m3u 的 id 五花八门（`CCTV1` / `cctv1` / `北京卫视` / `bjws`），
所以这里做一层匹配，然后把播放列表里的 `tvg-id` 批量改成本项目使用的 id。

匹配顺序（先严格后宽松）：
    1. id 完全相同
    2. id 忽略大小写相同            CCTV1   -> cctv1
    3. 命中频道注册表里的 alias     CCTV5+  -> cctv5plus
    4. 频道显示名完全相同           北京卫视 -> sat-beijing
    5. 去掉 HD/4K/空格/横线后相同    CCTV-5+HD 体育赛事 -> cctv5plus
    6. 一方包含另一方（长度 >= 3）   优漫卡通 -> js-cartoon（江苏优漫卡通）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import Channel

_ATTR_RE = re.compile(r'([a-zA-Z0-9-]+)="([^"]*)"')
_TVG_URL_RE = re.compile(r'(x-tvg-url=")([^"]*)(")')

# 这些标记只表示画质，不影响频道身份
_QUALITY_TOKENS = ("UHD", "HD", "4K", "8K", "超高清", "高清", "标清", "蓝光")
_SPACES_RE = re.compile(r"[\s\-_·•　|/]+")


def normalize_name(value: str) -> str:
    """统一成便于比较的形式：去画质标记、去空格横线、统一大写。"""
    text = (value or "").upper()
    for token in _QUALITY_TOKENS:
        text = text.replace(token, "")
    return _SPACES_RE.sub("", text)


@dataclass(frozen=True)
class M3UEntry:
    id: str
    name: str
    group: str
    display: str
    url: str

    def candidates(self) -> list[str]:
        return [c for c in (self.id, self.name, self.display) if c]


class Matcher:
    def __init__(self, channels: Iterable[Channel]) -> None:
        self.channels = list(channels)
        self.by_id = {c.id: c for c in self.channels}
        self.by_lower = {c.id.lower(): c for c in self.channels}
        self.by_alias: dict[str, Channel] = {}
        for channel in self.channels:
            for alias in channel.aliases:
                self.by_alias.setdefault(alias.lower(), channel)

    def match(self, entry: M3UEntry) -> tuple[Channel | None, str]:
        raw_id = (entry.id or "").strip()
        if raw_id and raw_id in self.by_id:
            return self.by_id[raw_id], "id 精确"
        if raw_id and raw_id.lower() in self.by_lower:
            return self.by_lower[raw_id.lower()], "id 忽略大小写"
        if raw_id and raw_id.lower() in self.by_alias:
            return self.by_alias[raw_id.lower()], "别名"

        for candidate in entry.candidates():
            for channel in self.channels:
                if channel.name == candidate:
                    return channel, "名称精确"
        for candidate in entry.candidates():
            for alias, channel in self.by_alias.items():
                if alias == candidate.lower():
                    return channel, "别名"

        for candidate in entry.candidates():
            key = normalize_name(candidate)
            if not key:
                continue
            for channel in self.channels:
                if normalize_name(channel.name) == key:
                    return channel, "名称归一"
            for alias, channel in self.by_alias.items():
                if normalize_name(alias) == key:
                    return channel, "别名归一"

        for candidate in entry.candidates():
            key = normalize_name(candidate)
            if len(key) < 3:
                continue
            for channel in self.channels:
                other = normalize_name(channel.name)
                if key in other or other in key:
                    return channel, "名称包含"
        return None, "未匹配"


def parse_m3u(text: str) -> list[M3UEntry]:
    entries: list[M3UEntry] = []
    pending: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(_ATTR_RE.findall(line))
            display = line.split(",", 1)[1].strip() if "," in line else ""
            pending = {
                "id": attrs.get("tvg-id", ""),
                "name": attrs.get("tvg-name", ""),
                "group": attrs.get("group-title", ""),
                "display": display,
            }
        elif line.startswith("#"):
            continue
        elif pending is not None:
            entries.append(M3UEntry(url=line, **pending))
            pending = None
    return entries


@dataclass
class MatchReport:
    total: int
    matched: int
    entries: list[dict]
    unmatched: list[dict]
    epg_unused: list[dict]

    @property
    def rate(self) -> float:
        return (self.matched / self.total * 100) if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "matched": self.matched,
            "rate": round(self.rate, 1),
            "entries": self.entries,
            "unmatched": self.unmatched,
            "epg_unused": self.epg_unused,
        }


def rewrite_m3u(text: str, matcher: Matcher, epg_url: str | None = None) -> tuple[str, MatchReport]:
    """把每个条目的 tvg-id 换成本项目的频道 id，并写入匹配报告。"""
    entries = parse_m3u(text)
    mapping: dict[int, tuple[Channel, str]] = {}
    unmatched: list[dict] = []
    used: set[str] = set()
    details: list[dict] = []

    for index, entry in enumerate(entries):
        channel, how = matcher.match(entry)
        if channel is None:
            unmatched.append({"id": entry.id, "display": entry.display, "group": entry.group})
            continue
        mapping[index] = (channel, how)
        used.add(channel.id)
        details.append(
            {
                "tvg_id": entry.id,
                "display": entry.display,
                "epg_id": channel.id,
                "epg_name": channel.name,
                "method": how,
            }
        )

    out: list[str] = []
    counter = -1
    for raw in text.splitlines():
        line = raw.strip()
        if epg_url and line.startswith("#EXTM3U"):
            if _TVG_URL_RE.search(line):
                line = _TVG_URL_RE.sub(lambda m: f"{m.group(1)}{epg_url}{m.group(3)}", line, count=1)
            else:
                line = line.rstrip() + f' x-tvg-url="{epg_url}"'
            out.append(line)
            continue
        if line.startswith("#EXTINF"):
            counter += 1
            if counter in mapping:
                channel, _ = mapping[counter]
                line = re.sub(r'tvg-id="[^"]*"', f'tvg-id="{channel.id}"', line, count=1)
            out.append(line)
            continue
        out.append(line)

    report = MatchReport(
        total=len(entries),
        matched=len(mapping),
        entries=details,
        unmatched=unmatched,
        epg_unused=[
            {"id": c.id, "name": c.name}
            for c in matcher.channels
            if c.id not in used
        ],
    )
    return "\n".join(out) + "\n", report
