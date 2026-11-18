"""极简 HTTP 客户端：重试、超时、gzip、磁盘缓存。

只用标准库 urllib，避免 requests / httpx 依赖。
"""

from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path


class FetchError(RuntimeError):
    """多次重试后仍无法获取内容。"""


def fetch_bytes(
    url: str,
    *,
    timeout: int = 30,
    retries: int = 3,
    user_agent: str = "cn-tv-epg/1.0",
    cache_path: Path | None = None,
) -> bytes:
    """下载 URL 内容；cache_path 命中时直接读缓存。"""
    if cache_path is not None and cache_path.exists():
        return cache_path.read_bytes()

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
            if encoding == "gzip":
                raw = gzip.decompress(raw)
            elif encoding == "deflate":
                raw = zlib.decompress(raw)
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(raw)
            return raw
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2.0 * attempt, 6.0))

    raise FetchError(f"获取失败（{retries} 次重试）：{url} -> {last_error}")


def fetch_text(url: str, **kwargs) -> str:
    """下载并解码为文本（站点均为 UTF-8）。"""
    raw = fetch_bytes(url, **kwargs)
    return raw.decode("utf-8", errors="replace")
