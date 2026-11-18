"""数据源适配层。

每个 provider 负责把一个数据源「翻译」成统一的 Programme 列表，
上层（cli / exporters）完全不关心数据来自 XMLTV 还是 HTML。
"""

from __future__ import annotations

from .base import Provider
from .tvmao import TvmaoProvider
from .xmltv import XmltvProvider

PROVIDERS: dict[str, type[Provider]] = {
    XmltvProvider.kind: XmltvProvider,
    TvmaoProvider.kind: TvmaoProvider,
}


def get_provider(kind: str) -> type[Provider]:
    try:
        return PROVIDERS[kind]
    except KeyError as exc:
        raise KeyError(f"未知的数据源类型：{kind}（可用：{', '.join(PROVIDERS)}）") from exc


__all__ = ["Provider", "TvmaoProvider", "XmltvProvider", "PROVIDERS", "get_provider"]
