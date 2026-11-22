"""把生成好的节目单发布到 Gitee 发行版（Release）附件。

为什么不用 Gitee 的 raw 直链？
    Gitee 对 raw 文件做了内容审核，超过约 64KB 无法扫描的文件一律返回
    451（The content may contain violation information）。节目单有 1MB，
    raw 走不通；而发行版附件走的是另一套存储，实测 1MB 文件可正常下载。

发布后的稳定地址（tag 固定为 data）：
    https://gitee.com/{owner}/cn-tv-epg/releases/download/data/epg.xml
    https://gitee.com/{owner}/cn-tv-epg/releases/download/data/epg.json

每次运行会先删掉同名旧附件再上传，所以地址始终不变。

环境变量：
    GITEE_USER   Gitee 用户名（必填）
    GITEE_TOKEN  Gitee 私人令牌（必填，需要 projects 权限）
    GITEE_REPO   仓库名，默认 cn-tv-epg
    GITEE_TAG    发行版 tag，默认 data
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = "https://gitee.com/api/v5"
TIMEOUT = 180


def _request(method: str, path: str, *, params: dict | None = None,
             data: bytes | None = None, content_type: str | None = None) -> tuple[int, dict]:
    url = f"{API}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", "cn-tv-epg/1.0")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:500]}
        return exc.code, payload


def _multipart(filename: str, content: bytes, content_type: str = "application/octet-stream") -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    buffer = io.BytesIO()
    buffer.write(f"--{boundary}\r\n".encode())
    buffer.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    buffer.write(f"Content-Type: {content_type}\r\n\r\n".encode())
    buffer.write(content)
    buffer.write(f"\r\n--{boundary}--\r\n".encode())
    return buffer.getvalue(), f"multipart/form-data; boundary={boundary}"


def recreate_release(owner: str, repo: str, token: str, tag: str) -> dict:
    """删掉同名发行版再重建。

    Gitee 没有「列出附件 id」的接口，没法单独替换某个附件；
    而下载地址只跟 tag 和文件名有关，所以整体重建最省事，地址保持不变。
    """
    status, payload = _request(
        "GET", f"/repos/{owner}/{repo}/releases/tags/{tag}", params={"access_token": token}
    )
    if status == 200:
        old_id = payload.get("id")
        _request(
            "DELETE", f"/repos/{owner}/{repo}/releases/{old_id}", params={"access_token": token}
        )
        print(f"已删除旧发行版 id={old_id}")

    status, payload = _request(
        "POST",
        f"/repos/{owner}/{repo}/releases",
        data=urllib.parse.urlencode(
            {
                "access_token": token,
                "tag_name": tag,
                "name": "节目单数据",
                "body": "每日自动更新的节目单（XMLTV / JSON）。由 GitHub Actions 发布。",
                "target_commitish": "master",
            }
        ).encode(),
        content_type="application/x-www-form-urlencoded",
    )
    if status not in (200, 201):
        raise RuntimeError(f"创建发行版失败 {status}: {payload}")
    return payload


def upload_asset(owner: str, repo: str, token: str, release_id: int, path: Path) -> dict:
    content = path.read_bytes()
    body, content_type = _multipart(path.name, content)
    status, payload = _request(
        "POST",
        f"/repos/{owner}/{repo}/releases/{release_id}/attach_files",
        params={"access_token": token},
        data=body,
        content_type=content_type,
    )
    if status not in (200, 201):
        raise RuntimeError(f"上传 {path.name} 失败 {status}: {str(payload)[:300]}")
    return payload


def main(argv: list[str]) -> int:
    files = [Path(item) for item in argv]
    missing = [str(f) for f in files if not f.exists()]
    if not files or missing:
        print(f"参数错误：找不到文件 {missing}", file=sys.stderr)
        return 2

    owner = os.environ.get("GITEE_USER", "").strip()
    token = os.environ.get("GITEE_TOKEN", "").strip()
    repo = os.environ.get("GITEE_REPO", "cn-tv-epg").strip()
    tag = os.environ.get("GITEE_TAG", "data").strip()
    if not owner or not token:
        print("未配置 GITEE_USER / GITEE_TOKEN，跳过 Gitee 发布")
        return 0

    release = recreate_release(owner, repo, token, tag)
    release_id = release["id"]
    print(f"发行版 tag={tag} id={release_id}")

    for path in files:
        result = upload_asset(owner, repo, token, release_id, path)
        print(f"  已上传 {path.name} ({path.stat().st_size:,} 字节)")
        print(f"    {result.get('browser_download_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
