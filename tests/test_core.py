"""单元测试：python -m unittest discover -s tests -v

只测纯逻辑（解析 / 清洗 / 导出），不打网络，保证 CI 里稳定。
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from epg.config import load_settings  # noqa: E402
from epg.exporters.jsonout import build_json  # noqa: E402
from epg.exporters.xmltvout import build_xmltv  # noqa: E402
from epg.models import Channel, Group, Guide, Programme  # noqa: E402
from epg.normalize import clean_title, is_placeholder, normalize, split_episode  # noqa: E402
from epg.providers.tvmao import TvmaoProvider  # noqa: E402
from epg.providers.xmltv import XmltvProvider, parse_xmltv_time  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")

TVMAO_HTML = """
<div class="epg mt30 mb10 clear">
  <ul id="pgrow">
    <li class="bg_f7"><div class="over_hide">
      <span class="am"> 00:55 </span>
      <span class="p_show"><a title="美好时代" href="/x">美好时代</a></span>
      <div class="rt dlink_menu"></div></div></li>
    <li><div class="over_hide">
      <span class="am"> 01:55 </span>
      <span class="p_show"><a title="家屋室的主人" href="/y">家屋室的主人</a></span>
      <div class="rt dlink_menu"></div></div></li>
    <li><div class="over_hide">
      <span class="pm"> 23:30 </span>
      <span class="p_show"><a title="晚间剧场" href="/z">晚间剧场</a></span>
      <div class="rt dlink_menu"></div></div></li>
  </ul>
</div>
"""


class TestNormalize(unittest.TestCase):
    def test_strip_ad_suffix(self):
        self.assertEqual(clean_title("今日说法-2026-209 --免费使用"), "今日说法-2026-209")
        self.assertEqual(clean_title("晚间新闻 --免费使用"), "晚间新闻")

    def test_collapse_whitespace(self):
        self.assertEqual(clean_title("  新闻　联播  "), "新闻 联播")

    def test_placeholder(self):
        self.assertTrue(is_placeholder("精彩节目-暂未提供节目预告信息"))
        self.assertFalse(is_placeholder("新闻联播"))

    def test_split_episode(self):
        self.assertEqual(split_episode("今日说法-2026-209"), ("今日说法", "2026-209"))
        self.assertEqual(split_episode("晚间新闻"), ("晚间新闻", None))

    def test_normalize_sorts_fills_and_dedupes(self):
        start = datetime(2026, 11, 18, 20, 0, tzinfo=TZ)
        items = [
            Programme("c", start, None, "晚间新闻"),
            Programme("c", start.replace(hour=19), None, "新闻联播"),
            Programme("c", start, None, "晚间新闻"),  # 重复
            Programme("c", start.replace(hour=21), None, "精彩节目-暂未提供节目预告信息"),
        ]
        result = normalize("c", items)
        self.assertEqual([p.title for p in result], ["新闻联播", "晚间新闻"])
        # 结束时间用下一条开始时间补齐
        self.assertEqual(result[0].stop, start)
        # 最后一条按 +60 分钟兜底
        self.assertEqual(result[1].stop, start.replace(hour=21))


class TestTvmaoProvider(unittest.TestCase):
    def setUp(self):
        settings = load_settings(ROOT)
        source = settings.source("tvmao")
        self.provider = TvmaoProvider(source, settings)

    def test_parse_day(self):
        items = self.provider.parse_day(TVMAO_HTML, "js-city", date(2026, 11, 18))
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].title, "美好时代")
        self.assertEqual(items[0].start.hour, 0)
        self.assertEqual(items[0].start.minute, 55)
        # 结束时间是下一条开始时间
        self.assertEqual(items[0].stop, items[1].start)
        # 最后一条 +60 分钟
        self.assertEqual((items[-1].stop - items[-1].start).seconds, 3600)

    def test_page_url(self):
        # w1 = 周一 … w7 = 周日，与 tvmao 周表一致
        self.assertTrue(self.provider.page_url("JSTV-JSTV3", date(2026, 11, 16)).endswith("-w1.html"))
        self.assertTrue(self.provider.page_url("JSTV-JSTV3", date(2026, 11, 22)).endswith("-w7.html"))

    def test_empty_page(self):
        self.assertEqual(self.provider.parse_day("<html></html>", "x", date(2026, 11, 18)), [])


class TestXmltv(unittest.TestCase):
    def test_parse_time(self):
        parsed = parse_xmltv_time("20261118001430 +0800", TZ)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.hour, 0)
        self.assertEqual(parsed.minute, 14)


class TestExporters(unittest.TestCase):
    def _guide(self) -> Guide:
        channel = Channel("cctv1", "CCTV-1 综合", "cctv", "xmltv-51zmt", "CCTV1")
        group = Group("cctv", "央视", (channel,))
        start = datetime(2026, 11, 18, 19, 0, tzinfo=TZ)
        items = [Programme("cctv1", start, start.replace(hour=19, minute=30), "新闻联播")]
        return Guide((group,), {"cctv1": items}, datetime(2026, 11, 18, 15, 0, tzinfo=TZ), TZ)

    def test_xmltv_shape(self):
        xml = build_xmltv(self._guide()).decode("utf-8")
        self.assertIn('<!DOCTYPE tv SYSTEM "xmltv.dtd">', xml)
        self.assertIn('<channel id="cctv1">', xml)
        self.assertIn("<display-name lang=\"zh\">CCTV-1 综合</display-name>", xml)
        self.assertIn('start="20261118190000 +0800"', xml)
        self.assertIn('stop="20261118193000 +0800"', xml)
        self.assertIn("新闻联播", xml)

    def test_json_shape(self):
        payload = build_json(self._guide())
        self.assertEqual(payload["stats"]["programmes"], 1)
        self.assertEqual(payload["channels"][0]["coverage"], ["2026-11-18", "2026-11-18"])
        row = payload["programmes"]["cctv1"][0]
        self.assertEqual(row["start"], "2026-11-18T19:00+08:00")
        self.assertEqual(row["date"], "2026-11-18")


class TestConfig(unittest.TestCase):
    def test_registry_loads(self):
        settings = load_settings(ROOT)
        self.assertEqual(len(settings.groups), 4)
        self.assertEqual(
            [g.id for g in settings.groups], ["cctv", "satellite", "jiangsu", "other"]
        )
        ids = [c.id for c in settings.channels]
        self.assertEqual(len(ids), len(set(ids)), "频道 id 必须唯一")
        self.assertIn("js-city", ids)
        self.assertIn("sat-jiangsu", ids)
        self.assertIn("kaku", ids)
        self.assertIn("middle-school", ids)

    def test_every_source_exists(self):
        settings = load_settings(ROOT)
        for channel in settings.channels:
            settings.source(channel.source)  # 不存在会抛 ConfigError


class TestMatching(unittest.TestCase):
    """m3u 播放列表与节目单 id 的对齐。"""

    SAMPLE = """#EXTM3U x-tvg-url="http://old.example/list.xml"
#EXTINF:-1 tvg-id="CCTV1" tvg-name="CCTV1" group-title="央视频道",CCTV-1HD 综合
http://example/1
#EXTINF:-1 tvg-id="CCTV5+" tvg-name="CCTV5+" group-title="央视频道",CCTV-5+HD 体育赛事
http://example/2
#EXTINF:-1 tvg-id="北京卫视" tvg-name="北京卫视" group-title="卫视频道",北京卫视4K
http://example/3
#EXTINF:-1 tvg-id="江苏体育休闲" tvg-name="江苏体育休闲" group-title="江苏频道",江苏体育休闲
http://example/4
#EXTINF:-1 tvg-id="不存在的频道" tvg-name="不存在的频道" group-title="其它频道",不存在的频道
http://example/5
"""

    def setUp(self):
        from epg.matching import Matcher

        self.settings = load_settings(ROOT)
        self.matcher = Matcher(self.settings.channels)

    def test_normalize_name(self):
        from epg.matching import normalize_name

        self.assertEqual(normalize_name("CCTV-1HD 综合"), "CCTV1综合")
        self.assertEqual(normalize_name("湖南卫视4K"), "湖南卫视")
        self.assertEqual(normalize_name("cctv5+"), "CCTV5+")

    def test_parse_m3u(self):
        from epg.matching import parse_m3u

        entries = parse_m3u(self.SAMPLE)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0].id, "CCTV1")
        self.assertEqual(entries[0].url, "http://example/1")

    def test_match_strategies(self):
        from epg.matching import parse_m3u

        entries = parse_m3u(self.SAMPLE)
        matched = [self.matcher.match(e) for e in entries]
        self.assertEqual(matched[0][0].id, "cctv1")       # id 忽略大小写
        self.assertEqual(matched[1][0].id, "cctv5plus")   # 别名
        self.assertEqual(matched[2][0].id, "sat-beijing")  # 名称精确
        self.assertEqual(matched[3][0].id, "js-sports")   # 别名（语序不同）
        self.assertIsNone(matched[4][0])                  # 节目单里没有

    def test_rewrite(self):
        from epg.matching import rewrite_m3u

        patched, report = rewrite_m3u(self.SAMPLE, self.matcher, "https://epg.example/epg.xml")
        self.assertIn('x-tvg-url="https://epg.example/epg.xml"', patched)
        self.assertIn('tvg-id="cctv1"', patched)
        self.assertIn('tvg-id="sat-beijing"', patched)
        self.assertNotIn('tvg-id="CCTV1"', patched)
        # 未匹配的条目原样保留，流地址不动
        self.assertIn('tvg-id="不存在的频道"', patched)
        self.assertIn("http://example/5", patched)
        self.assertEqual(report.total, 5)
        self.assertEqual(report.matched, 4)
        self.assertEqual(len(report.unmatched), 1)


if __name__ == "__main__":
    unittest.main()
