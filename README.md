# cn-tv-epg · 中文电视节目单

一个**可维护、可自动更新**的电视节目单（EPG）项目，覆盖：

| 分组 | 频道数 | 说明 |
| --- | --- | --- |
| 央视 | 19 | CCTV-1 ~ CCTV-17、CCTV-5+、CCTV-4K |
| 卫视 | 43 | 全国省级上星频道 + 金鹰卡通 / 中国教育台等 |
| 江苏地方台 | 38 | 江苏城市/综艺/影视/新闻…，南京、苏州、无锡、常州、南通、徐州、扬州、镇江、泰州、盐城、淮安、连云港、宿迁及部分县台 |
| 其它频道 | 4 | 卡酷少儿、中学生、东方财经、生活时尚 |

输出两种通用格式，任何播放器、App、电视端都能直接吃：

- `dist/epg.xml` —— 标准 **XMLTV**，TiviMate / Kodi / IPTV Pro / DIYP 等通用
- `dist/epg.json` —— 结构化 **JSON**，方便二次开发
- `web/index.html` —— 自带的网页查看器，按 央视 / 卫视 / 江苏地方台 分栏

> 数据抓取自公开的电视节目预告服务，仅供个人学习与自用，版权归各电视台所有。

---

## 快速开始

只需要 **Python 3.11+**，不装任何第三方库（无 pip install）。

```bash
# 生成今晚到明天的节目单
python -m epg build

# 从今天起生成 3 天
python -m epg build --days 3

# 本地预览网页
python -m epg serve
# 浏览器打开 http://127.0.0.1:8899/web/index.html
```

首次运行约 1 分钟（江苏地方台是逐频道抓取），之后有本地缓存会快很多。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `python -m epg build` | 抓取并生成 `dist/epg.xml`、`dist/epg.json` 与历史快照 |
| `python -m epg build --days 3` | 指定天数 |
| `python -m epg build --group jiangsu` | 只生成某个分组（`cctv` / `satellite` / `jiangsu`） |
| `python -m epg build --refresh` | 忽略缓存，强制重新抓取 |
| `python -m epg patch-m3u <地址或文件>` | 把 m3u 播放列表的 `tvg-id` 对齐到本节目单 |
| `python -m epg channels` | 查看频道注册表 |
| `python -m epg validate` | 检查上游是否改名（防止静默失效） |
| `python -m epg discover --province 320000` | 列出江苏全部可抓频道（新增频道时用） |
| `python -m epg resolve --keyword 江苏` | 在上游源里搜频道名 |
| `python -m epg serve` | 本地预览网页 |
| `python -m epg clean` | 清空抓取缓存 |

## 自动更新

`.github/workflows/update.yml` 已配好：

- 每天北京时间 **06:30** 自动抓取并提交 `dist/` 与当日快照；
- 也可以在 Actions 页面点 **Run workflow** 手动触发；
- 如果你在仓库设置里开启 **GitHub Pages**（Source: GitHub Actions），
  还会顺手发布一个网页版节目单。

不需要改任何代码，推上去就会自己更新。

## 在播放器里使用

把下面任一地址加到播放器的 EPG / 节目单设置里（把 `<用户名>`、`<仓库名>` 换成你的）：

```
https://raw.githubusercontent.com/<用户名>/<仓库名>/main/dist/epg.xml
```

若是私有仓库，用本地路径也行：`dist/epg.xml`。

## 对接本地 m3u 播放列表（重点）

播放器是按 `tvg-id` 去节目单里找频道的，而各家 m3u 的 id 写法五花八门
（`CCTV1` / `cctv1` / `北京卫视` / `bjws`）。项目自带对齐工具：

```bash
python -m epg patch-m3u http://192.168.3.1:8189/unicompublic.m3u --verbose
```

它会：

1. 按 `id → 别名 → 频道名 → 去画质词归一` 的顺序匹配；
2. 把每条 `tvg-id` 改写成本项目使用的 id（`cctv1` / `sat-beijing` / `js-city` …）；
3. 把播放列表头部的 `x-tvg-url` 换成你的节目单地址；
4. 输出 `dist/<文件名>.epg.m3u` 和 `dist/<文件名>.epg.report.json`。

流地址一律不动，只改 EPG 相关字段。把生成的 m3u 丢给播放器即可，节目单就能对上。

不匹配的频道会列在报告里（通常是节目单没有收录的频道，播放器只是不显示节目，不影响播放）。

## 项目结构

```
cn-tv-epg/
├─ config/
│  ├─ settings.toml      # 全局设置 + 数据源
│  └─ channels.toml      # ★ 频道注册表（唯一需要手工改的文件）
├─ epg/
│  ├─ cli.py             # 命令行
│  ├─ config.py          # 配置加载与校验
│  ├─ models.py          # 数据模型
│  ├─ normalize.py       # 标题清洗 / 排序 / 补结束时间
│  ├─ http.py            # 带重试与缓存的下载器
│  ├─ providers/         # 数据源适配层
│  │  ├─ xmltv.py        #   51zmt XMLTV（央视 + 卫视，整包一次拉取）
│  │  ├─ tvmao.py        #   电视猫（江苏地方台、卡酷少儿，按频道抓）
│  │  └─ diyp.py         #   51zmt 按名查询（中学生、东方财经、生活时尚）
│  └─ exporters/         # 输出层
│     ├─ xmltvout.py
│     └─ jsonout.py
├─ web/                  # 网页查看器（纯前端，零依赖）
├─ dist/                 # 生成结果（epg.xml / epg.json）
├─ data/archive/         # 每日历史快照
└─ tests/                # 单元测试
```

## 维护

新增 / 修改频道、更换数据源、排错，见 [docs/维护指南.md](docs/维护指南.md)。

## 开发

```bash
python -m unittest discover -s tests -v
```

## 许可

[MIT](LICENSE)
