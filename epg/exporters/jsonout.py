"""导出为 JSON —— 给网页、App、脚本用的结构化节目单。

结构（简约、稳定，方便二次开发）：

{
  "generator": "cn-tv-epg",
  "version": "1.0.0",
  "generated_at": "2026-11-18T15:40:00+08:00",
  "timezone": "Asia/Shanghai",
  "dates": ["2026-11-18", "2026-11-19"],
  "stats": {"channels": 100, "programmes": 8000},
  "groups": [{"id": "cctv", "name": "央视", "channels": ["cctv1", ...]}],
  "channels": [
     {"id": "cctv1", "name": "CCTV-1 综合", "group": "cctv",
      "coverage": ["2026-11-18", "2026-11-19"], "count": 32}
  ],
  "programmes": {
     "cctv1": [{"date": "2026-11-18", "start": "2026-11-18T00:14:00+08:00",
                "end": "2026-11-18T00:37:00+08:00", "title": "人口", "episode": "2026-46"}]
  }
}
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import __version__
from ..models import Guide
from ..normalize import coverage, split_episode


def build_json(guide: Guide) -> dict:
    channels: list[dict] = []
    programmes: dict[str, list[dict]] = {}

    for channel in guide.channels:
        items = guide.programmes.get(channel.id, [])
        start_date, end_date = coverage(items)
        channels.append(
            {
                "id": channel.id,
                "name": channel.name,
                "group": channel.group,
                "logo": channel.logo,
                "coverage": [start_date, end_date] if start_date else [],
                "count": len(items),
            }
        )
        rows: list[dict] = []
        for programme in items:
            base, episode = split_episode(programme.title)
            row = {
                "date": programme.date_key,
                "start": programme.start.isoformat(timespec="minutes"),
                "end": programme.stop.isoformat(timespec="minutes") if programme.stop else None,
                "title": programme.title,
            }
            if episode:
                row["episode"] = episode
                row["title_base"] = base
            rows.append(row)
        if rows:
            programmes[channel.id] = rows

    return {
        "generator": "cn-tv-epg",
        "version": __version__,
        "generated_at": guide.generated_at.isoformat(timespec="seconds"),
        "timezone": str(guide.timezone),
        "dates": guide.dates,
        "stats": {
            "groups": len(guide.groups),
            "channels": len(guide.channels),
            "channels_with_data": len(programmes),
            "programmes": guide.total,
        },
        "groups": [
            {"id": g.id, "name": g.name, "channels": [c.id for c in g.channels]}
            for g in guide.groups
        ],
        "channels": channels,
        "programmes": programmes,
    }


def write_json(guide: Guide, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_json(guide)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )
    return path
