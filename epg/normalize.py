"""节目单归一化：清洗标题、合并、排序、补全结束时间。

所有数据源共用的「统一口径」都在这里，保证输出格式稳定，
上层播放器 / 网页端不需要为某个源做特殊处理。
"""

from __future__ import annotations

import re
from datetime import timedelta

from .models import Programme

# 上游为了防盗链 / 打广告会在标题后面加尾巴
_AD_SUFFIX_RE = re.compile(r"\s*(?:-{1,2}\s*免费使用|（?免费使用）?)\s*$")
_WS_RE = re.compile(r"[\s\u3000]+")
# 明显的「没有节目信息」占位
_PLACEHOLDER_HINTS = ("暂未提供", "暂无节目", "精彩节目", "节目预告信息", "未提供")
_EPISODE_RE = re.compile(r"[-－](\d{4})[-－](\d{1,3})$")


def clean_title(raw: str) -> str:
    """去掉广告尾巴、压缩空白。保留剧集编号（如「今日说法-2026-209」）。"""
    title = (raw or "").replace("\u3000", " ")
    title = _AD_SUFFIX_RE.sub("", title)
    title = _WS_RE.sub(" ", title).strip()
    return title


def is_placeholder(title: str) -> bool:
    return any(hint in title for hint in _PLACEHOLDER_HINTS)


def split_episode(title: str) -> tuple[str, str | None]:
    """把「今日说法-2026-209」拆成 (今日说法, 2026-209)。无编号时返回 (title, None)。"""
    match = _EPISODE_RE.search(title)
    if not match:
        return title, None
    return title[: match.start()].strip(), f"{match.group(1)}-{match.group(2)}"


def normalize(channel_id: str, programmes: list[Programme], *, drop_placeholders: bool = True) -> list[Programme]:
    """清洗 + 排序 + 补结束时间 + 去重。"""
    cleaned: list[Programme] = []
    for item in programmes:
        title = clean_title(item.title)
        if not title:
            continue
        if drop_placeholders and is_placeholder(title):
            continue
        cleaned.append(
            Programme(
                channel_id=channel_id,
                start=item.start,
                stop=item.stop,
                title=title,
                desc=item.desc,
                category=item.category,
            )
        )

    cleaned.sort(key=lambda p: p.start)

    # 同一时间同一标题视为重复（不同源合并时常见）
    deduped: list[Programme] = []
    for item in cleaned:
        duplicate = any(
            prev.start == item.start and prev.title == item.title for prev in deduped[-3:]
        )
        if not duplicate:
            deduped.append(item)

    # 补结束时间：优先下一条的开始时间
    filled: list[Programme] = []
    for index, item in enumerate(deduped):
        stop = item.stop
        if stop is None:
            if index + 1 < len(deduped):
                stop = deduped[index + 1].start
            else:
                stop = item.start + timedelta(minutes=60)
        if stop <= item.start:
            stop = item.start + timedelta(minutes=60)
        filled.append(
            Programme(
                channel_id=channel_id,
                start=item.start,
                stop=stop,
                title=item.title,
                desc=item.desc,
                category=item.category,
            )
        )
    return filled


def coverage(programmes: list[Programme]) -> tuple[str | None, str | None]:
    """返回节目单覆盖的起止日期（YYYY-MM-DD）。"""
    if not programmes:
        return None, None
    dates = sorted({p.date_key for p in programmes})
    return dates[0], dates[-1]
