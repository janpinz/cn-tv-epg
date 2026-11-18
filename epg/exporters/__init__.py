"""输出格式：XMLTV / JSON / 静态网页数据。"""

from __future__ import annotations

from .jsonout import write_json
from .xmltvout import write_xmltv

__all__ = ["write_json", "write_xmltv"]
