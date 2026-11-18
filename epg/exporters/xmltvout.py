"""导出为 XMLTV（.xml）—— 几乎所有播放器 / 电视端 App 都认的通用格式。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .. import __version__
from ..models import Guide, fmt_xmltv_time

GENERATOR_URL = "https://github.com/janpinz/cn-tv-epg"


def _display_names(channel) -> list[str]:
    """别名优先、规范名兜底，去重保序。"""
    names: list[str] = []
    for name in (*channel.aliases, channel.name):
        name = (name or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def build_xmltv(guide: Guide) -> bytes:
    tv = ET.Element(
        "tv",
        {
            "generator-info-name": f"cn-tv-epg {__version__}",
            "generator-info-url": GENERATOR_URL,
            "date": guide.generated_at.strftime("%Y%m%d%H%M%S %z"),
        },
    )

    for channel in guide.channels:
        node = ET.SubElement(tv, "channel", {"id": channel.id})
        # 有的播放器不看 tvg-id，而是拿播放列表里的频道名（tvg-name）去比对
        # <display-name>。所以把别名排在前面、规范名放最后，两种匹配都能命中。
        for name in _display_names(channel):
            ET.SubElement(node, "display-name", {"lang": "zh"}).text = name
        if channel.logo:
            ET.SubElement(node, "icon", {"src": channel.logo})

    for channel in guide.channels:
        for programme in guide.programmes.get(channel.id, ()):
            attrs = {
                "start": fmt_xmltv_time(programme.start),
                "channel": channel.id,
            }
            if programme.stop is not None:
                attrs["stop"] = fmt_xmltv_time(programme.stop)
            node = ET.SubElement(tv, "programme", attrs)
            ET.SubElement(node, "title", {"lang": "zh"}).text = programme.title
            if programme.desc:
                ET.SubElement(node, "desc", {"lang": "zh"}).text = programme.desc
            if programme.category:
                ET.SubElement(node, "category", {"lang": "zh"}).text = programme.category

    ET.indent(tv, space="  ")
    body = ET.tostring(tv, encoding="unicode")
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'
    )
    return (header + body + "\n").encode("utf-8")


def write_xmltv(guide: Guide, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_xmltv(guide))
    return path
