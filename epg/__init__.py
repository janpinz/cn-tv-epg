"""cn-tv-epg —— 可维护、可自动更新的中文电视节目单（EPG）生成器。

数据流：
    config/channels.toml  ──> providers（xmltv / tvmao）──> 归一化 ──> dist/epg.xml + dist/epg.json

设计目标是「零第三方依赖」：只使用 Python 3.11+ 标准库，
这样 GitHub Actions 里不需要 pip install，本地也不需要虚拟环境。
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
