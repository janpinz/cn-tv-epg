"""命令行入口：python -m epg <命令>

常用：
    python -m epg build                # 抓取 + 生成（默认命令）
    python -m epg build --days 3       # 生成从今天起 3 天
    python -m epg validate             # 校验配置与上游频道是否仍然有效
    python -m epg channels             # 查看频道清单
    python -m epg discover --province 320000   # 列出江苏所有可抓频道
    python -m epg serve                # 本地预览网页
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .config import ConfigError, Settings, load_settings
from .exporters import write_json, write_xmltv
from .models import Guide, Programme
from .normalize import normalize
from .providers import get_provider

# patch-m3u 默认写进播放列表头部的节目单地址
DEFAULT_EPG_URL = "https://raw.githubusercontent.com/janpinz/cn-tv-epg/main/dist/epg.xml"


# --------------------------------------------------------------------------
# 公共
# --------------------------------------------------------------------------
def _settings(args: argparse.Namespace) -> Settings:
    return load_settings(args.root)


def _target_dates(settings: Settings, days: int | None) -> list[date]:
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    ahead = settings.days_ahead if days is None else max(0, days - 1)
    start = today - timedelta(days=max(0, settings.days_back))
    return [start + timedelta(days=offset) for offset in range((today + timedelta(days=ahead) - start).days + 1)]


def _collect(settings: Settings, dates: list[date], only_groups: set[str] | None) -> dict[str, list[Programme]]:
    """按数据源分组抓取，返回 {channel_id: 归一化后的节目列表}。"""
    by_source: dict[str, list] = {}
    for group in settings.groups:
        if only_groups and group.id not in only_groups:
            continue
        for channel in group.channels:
            by_source.setdefault(channel.source, []).append(channel)

    collected: dict[str, list[Programme]] = {}
    for source_id, channels in by_source.items():
        source = settings.source(source_id)
        if not source.enabled:
            print(f"  · 跳过已停用数据源 {source_id}")
            continue
        provider_cls = get_provider(source.kind)
        provider = provider_cls(source, settings)
        print(f"  · {source_id}（{source.kind}）：{len(channels)} 个频道, {len(dates)} 天")
        started = time.time()
        try:
            raw = provider.fetch(channels, dates)
        except Exception as exc:  # 单源失败不影响其他源
            print(f"    ! 抓取失败：{exc}")
            continue
        missing = [c.id for c in channels if c.id not in raw]
        for channel in channels:
            items = raw.get(channel.id, [])
            if not items:
                continue
            cleaned = normalize(channel.id, items)
            if cleaned:
                collected[channel.id] = cleaned
        print(f"    ✓ {len(raw)}/{len(channels)} 个频道有数据，耗时 {time.time() - started:.1f}s")
        if missing:
            preview = ", ".join(missing[:8])
            more = f" 等 {len(missing)} 个" if len(missing) > 8 else ""
            print(f"    · 无节目数据：{preview}{more}")
    return collected


def _print_summary(guide: Guide) -> None:
    print("\n频道覆盖：")
    header = f"  {'分组':<8}{'频道':>6}{'有数据':>8}{'节目数':>8}"
    print(header)
    for group in guide.groups:
        with_data = sum(1 for c in group.channels if guide.count(c.id))
        total = sum(guide.count(c.id) for c in group.channels)
        print(f"  {group.name:<8}{len(group.channels):>6}{with_data:>8}{total:>8}")
    print(f"  {'合计':<8}{len(guide.channels):>6}"
          f"{sum(1 for c in guide.channels if guide.count(c.id)):>8}{guide.total:>8}")


# --------------------------------------------------------------------------
# 命令：build
# --------------------------------------------------------------------------
def cmd_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if args.refresh:
        cache = settings.raw_dir()
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)
            print(f"已清空缓存：{cache}")

    dates = _target_dates(settings, args.days)
    print(f"生成时间：{datetime.now(ZoneInfo(settings.timezone)):%Y-%m-%d %H:%M:%S %z}")
    print(f"目标日期：{dates[0]} ~ {dates[-1]}（共 {len(dates)} 天）")

    only = set(args.group) if args.group else None
    print("\n抓取：")
    collected = _collect(settings, dates, only)

    guide = Guide(
        groups=settings.groups,
        programmes=collected,
        generated_at=datetime.now(ZoneInfo(settings.timezone)),
        timezone=ZoneInfo(settings.timezone),
    )
    _print_summary(guide)

    if guide.total == 0:
        print("\n✗ 没有抓到任何节目，未生成文件。请检查网络或数据源。")
        return 1

    xml_path = write_xmltv(guide, settings.out_dir / "epg.xml")
    json_path = write_json(guide, settings.out_dir / "epg.json")
    print(f"\n输出：\n  {xml_path}\n  {json_path}")

    if settings.archive and not args.no_archive:
        stamp = guide.generated_at.strftime("%Y-%m-%d")
        archive_path = settings.archive_dir / stamp / "epg.json"
        write_json(guide, archive_path)
        print(f"  {archive_path}（历史快照）")
    return 0


# --------------------------------------------------------------------------
# 命令：channels
# --------------------------------------------------------------------------
def cmd_channels(args: argparse.Namespace) -> int:
    settings = _settings(args)
    print(f"共 {len(settings.groups)} 组 / {len(settings.channels)} 个频道\n")
    for group in settings.groups:
        print(f"[{group.name}] ({group.id})")
        for channel in group.channels:
            print(f"  {channel.id:<16} {channel.name:<16} {channel.source:<14} {channel.ref}")
        print()
    return 0


# --------------------------------------------------------------------------
# 命令：validate
# --------------------------------------------------------------------------
def cmd_validate(args: argparse.Namespace) -> int:
    """检查注册表里的每个 ref 能否在上游找到，防止上游改名后静默失效。"""
    settings = _settings(args)
    print(f"校验 {len(settings.channels)} 个频道……\n")
    problems = 0
    for group in settings.groups:
        for channel in group.channels:
            source = settings.source(channel.source)
            if source.kind != "xmltv":
                continue
            provider = get_provider(source.kind)(source, settings)
            names = provider.available_names()
            if channel.ref not in names:
                problems += 1
                hint = _closest(channel.ref, names)
                print(f"  ✗ {channel.id:<16} ref=\"{channel.ref}\" 在上游不存在"
                      + (f"，最接近：{hint}" if hint else ""))
    if problems == 0:
        print("  ✓ XMLTV 源的所有频道名均可匹配")
    print(f"\n{'✗ 有 %d 个频道需要修正' % problems if problems else '✓ 配置正常'}")
    return 1 if problems else 0


def _closest(target: str, candidates: list[str]) -> str | None:
    import difflib

    match = difflib.get_close_matches(target, candidates, n=1, cutoff=0.5)
    return match[0] if match else None


# --------------------------------------------------------------------------
# 命令：discover / resolve
# --------------------------------------------------------------------------
def cmd_discover(args: argparse.Namespace) -> int:
    settings = _settings(args)
    source = settings.source(args.source)
    provider = get_provider(source.kind)(source, settings)
    if not hasattr(provider, "discover"):
        print(f"数据源 {source.id} 不支持自动发现频道")
        return 1
    items = provider.discover(args.province)
    print(f"共发现 {len(items)} 个频道（可直接粘进 config/channels.toml）：\n")
    for code, name in items:
        print(f'  {{ id = "?", name = "{name}", source = "{source.id}", ref = "{code}" }},')
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    settings = _settings(args)
    source = settings.source(args.source)
    provider = get_provider(source.kind)(source, settings)
    if not hasattr(provider, "available_names"):
        print(f"数据源 {source.id} 不支持名称匹配")
        return 1
    names = provider.available_names()
    if args.keyword:
        hits = [n for n in names if args.keyword in n]
        print(f"匹配 \"{args.keyword}\" 的频道（{len(hits)}）：")
        for name in hits:
            print(f"  {name}")
        return 0 if hits else 1
    print(f"共 {len(names)} 个频道：")
    for name in names:
        print(f"  {name}")
    return 0


# --------------------------------------------------------------------------
# 命令：patch-m3u
# --------------------------------------------------------------------------
def cmd_patch_m3u(args: argparse.Namespace) -> int:
    """把外部 m3u 的 tvg-id 换成本项目 EPG 的频道 id。"""
    import json

    from .http import fetch_text
    from .matching import Matcher, rewrite_m3u

    settings = _settings(args)
    source = args.source
    if source.startswith(("http://", "https://")):
        print(f"读取播放列表：{source}")
        text = fetch_text(
            source,
            timeout=settings.timeout,
            retries=settings.retries,
            user_agent=settings.user_agent,
        )
    else:
        path = Path(source)
        if not path.is_absolute():
            path = settings.root / path
        if not path.exists():
            print(f"找不到播放列表：{path}", file=sys.stderr)
            return 2
        print(f"读取播放列表：{path}")
        text = path.read_text(encoding="utf-8-sig", errors="replace")

    matcher = Matcher(settings.channels)
    epg_url = args.epg_url or DEFAULT_EPG_URL
    patched, report = rewrite_m3u(text, matcher, epg_url)

    out_path = Path(args.out) if args.out else None
    if out_path is None:
        stem = args.name or Path(source.split("?")[0]).stem or "playlist"
        out_path = settings.out_dir / f"{Path(stem).stem}.epg.m3u"
    if not out_path.is_absolute():
        out_path = settings.root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(patched, encoding="utf-8")

    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n条目 {report.total} 条，已对齐 {report.matched} 条（{report.rate:.1f}%）")
    if report.unmatched:
        print(f"\n未对齐 {len(report.unmatched)} 条（节目单里没有这些频道，播放器会不显示节目）：")
        for item in report.unmatched:
            print(f"  {item['id'] or '(无 id)':<14} {item['display']}")
    if args.verbose:
        print("\n对齐明细：")
        for item in report.entries:
            print(f"  {item['tvg_id'] or '(无 id)':<14} -> {item['epg_id']:<14} ({item['method']}) {item['display']}")
        if report.epg_unused:
            print(f"\n节目单里未被播放列表使用：{len(report.epg_unused)} 个")
    print(f"\n输出：\n  {out_path}\n  {report_path}")
    return 0


DEFAULT_EPG_URL = "https://raw.githubusercontent.com/janpinz/cn-tv-epg/main/dist/epg.xml"


# --------------------------------------------------------------------------
# 命令：serve
# --------------------------------------------------------------------------
def cmd_serve(args: argparse.Namespace) -> int:
    import functools
    import http.server
    import socketserver

    root = Path(args.root).resolve()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"本地预览：http://127.0.0.1:{args.port}/web/index.html")
        print("按 Ctrl+C 停止")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


# --------------------------------------------------------------------------
# 命令：clean
# --------------------------------------------------------------------------
def cmd_clean(args: argparse.Namespace) -> int:
    settings = _settings(args)
    cache = settings.raw_dir()
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
        print(f"已删除缓存目录：{cache}")
    else:
        print("缓存目录不存在，无需清理")
    return 0


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epg",
        description="中文电视节目单生成器（央视 / 卫视 / 江苏地方台）",
    )
    parser.add_argument("--version", action="version", version=f"cn-tv-epg {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", default=".", help="项目根目录（默认当前目录）")

    p_build = sub.add_parser("build", help="抓取并生成节目单（默认命令）")
    add_common(p_build)
    p_build.add_argument("--days", type=int, default=None, help="从今天起生成多少天（默认取配置）")
    p_build.add_argument("--group", action="append", help="只生成指定分组，可重复，如 --group cctv")
    p_build.add_argument("--refresh", action="store_true", help="忽略磁盘缓存，强制重新抓取")
    p_build.add_argument("--no-archive", action="store_true", help="不写历史快照")
    p_build.set_defaults(func=cmd_build)

    p_channels = sub.add_parser("channels", help="列出频道注册表")
    add_common(p_channels)
    p_channels.set_defaults(func=cmd_channels)

    p_validate = sub.add_parser("validate", help="校验频道 ref 是否仍在上游存在")
    add_common(p_validate)
    p_validate.set_defaults(func=cmd_validate)

    p_discover = sub.add_parser("discover", help="列出某省全部可抓频道（用于新增频道）")
    add_common(p_discover)
    p_discover.add_argument("--source", default="tvmao")
    p_discover.add_argument("--province", default="320000", help="省份代码，江苏=320000")
    p_discover.set_defaults(func=cmd_discover)

    p_resolve = sub.add_parser("resolve", help="在上游源里搜索频道名")
    add_common(p_resolve)
    p_resolve.add_argument("--source", default="xmltv-51zmt")
    p_resolve.add_argument("--keyword", default=None)
    p_resolve.set_defaults(func=cmd_resolve)

    p_patch = sub.add_parser("patch-m3u", help="把 m3u 播放列表的 tvg-id 对齐到本节目单")
    add_common(p_patch)
    p_patch.add_argument("source", help="m3u 地址或本地文件路径")
    p_patch.add_argument("--out", default=None, help="输出路径（默认 dist/<文件名>.epg.m3u）")
    p_patch.add_argument("--name", default=None, help="输出文件名（不含扩展名）")
    p_patch.add_argument("--epg-url", default=None, help="写进播放列表头部的节目单地址")
    p_patch.add_argument("--verbose", action="store_true", help="打印每条对齐明细")
    p_patch.set_defaults(func=cmd_patch_m3u)

    p_serve = sub.add_parser("serve", help="本地预览网页")
    add_common(p_serve)
    p_serve.add_argument("--port", type=int, default=8899)
    p_serve.set_defaults(func=cmd_serve)

    p_clean = sub.add_parser("clean", help="删除抓取缓存")
    add_common(p_clean)
    p_clean.set_defaults(func=cmd_clean)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args(["build", *(argv or [])])
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
