"""配置加载与校验。

两个文件：
  config/settings.toml —— 全局设置 + 数据源
  config/channels.toml —— 频道注册表

用 tomllib（Python 3.11+ 标准库）解析，因此没有 PyYAML 之类的依赖。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .models import Channel, Group

DEFAULT_CONFIG_DIR = Path("config")


class ConfigError(RuntimeError):
    """配置有误时抛出，错误信息直接面向使用者。"""


@dataclass(frozen=True)
class Source:
    id: str
    kind: str  # xmltv / tvmao
    url: str | None = None
    base: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class Settings:
    root: Path
    timezone: str = "Asia/Shanghai"
    days_back: int = 0
    days_ahead: int = 1
    timeout: int = 30
    retries: int = 3
    delay: float = 0.6
    user_agent: str = "cn-tv-epg/1.0"
    out_dir: Path = Path("dist")
    archive_dir: Path = Path("data/archive")
    archive: bool = True
    sources: tuple[Source, ...] = ()
    groups: tuple[Group, ...] = ()

    def source(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise ConfigError(f"未知数据源：{source_id}（请检查 config/settings.toml）")

    @property
    def channels(self) -> tuple[Channel, ...]:
        return tuple(ch for g in self.groups for ch in g.channels)

    def raw_dir(self) -> Path:
        return self.root / "data" / "raw"


def _load_toml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"找不到配置文件：{path}")
    try:
        with path.open("rb") as fp:
            return tomllib.load(fp)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - 语法错误时给出可读提示
        raise ConfigError(f"{path} 语法错误：{exc}") from exc


def load_settings(root: Path | str = ".", config_dir: Path | str = DEFAULT_CONFIG_DIR) -> Settings:
    root = Path(root).resolve()
    config_dir = (root / config_dir) if not Path(config_dir).is_absolute() else Path(config_dir)

    raw_settings = _load_toml(config_dir / "settings.toml")
    raw_channels = _load_toml(config_dir / "channels.toml")

    general = raw_settings.get("general", {})
    fetch = raw_settings.get("fetch", {})
    output = raw_settings.get("output", {})

    sources: list[Source] = []
    for item in raw_settings.get("sources", []):
        for key in ("id", "kind"):
            if key not in item:
                raise ConfigError(f"[[sources]] 缺少字段 {key}：{item}")
        sources.append(
            Source(
                id=item["id"],
                kind=item["kind"],
                url=item.get("url"),
                base=item.get("base"),
                enabled=bool(item.get("enabled", True)),
            )
        )

    known = {s.id for s in sources}
    groups: list[Group] = []
    seen_ids: set[str] = set()

    for raw_group in raw_channels.get("group", []):
        gid = raw_group.get("id")
        gname = raw_group.get("name", gid)
        if not gid:
            raise ConfigError("[[group]] 缺少 id")
        channels: list[Channel] = []
        for item in raw_group.get("channels", []):
            for key in ("id", "name", "source", "ref"):
                if not item.get(key):
                    raise ConfigError(f"频道 {item} 缺少字段 {key}")
            cid = item["id"]
            if cid in seen_ids:
                raise ConfigError(f"频道 id 重复：{cid}")
            if item["source"] not in known:
                raise ConfigError(f"频道 {cid} 引用了未知数据源 {item['source']}")
            seen_ids.add(cid)
            aliases = item.get("alias", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            channels.append(
                Channel(
                    id=cid,
                    name=item["name"],
                    group=gid,
                    source=item["source"],
                    ref=item["ref"],
                    logo=item.get("logo"),
                    aliases=tuple(aliases),
                )
            )
        groups.append(Group(id=gid, name=gname, channels=tuple(channels)))

    if not groups:
        raise ConfigError("config/channels.toml 里没有任何频道分组")

    return Settings(
        root=root,
        timezone=general.get("timezone", "Asia/Shanghai"),
        days_back=int(general.get("days_back", 0)),
        days_ahead=int(general.get("days_ahead", 1)),
        timeout=int(fetch.get("timeout", 30)),
        retries=int(fetch.get("retries", 3)),
        delay=float(fetch.get("delay", 0.6)),
        user_agent=fetch.get("user_agent", "cn-tv-epg/1.0"),
        out_dir=root / output.get("dir", "dist"),
        archive_dir=root / output.get("archive_dir", "data/archive"),
        archive=bool(output.get("archive", True)),
        sources=tuple(sources),
        groups=tuple(groups),
    )
