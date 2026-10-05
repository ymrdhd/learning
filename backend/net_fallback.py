# 能力契约｜直连兜底（hosts 把 github 指向 127.0.0.1 时，用 DoH 解析真实 IP + SNI 直连）
# 职责：给 updater / publish 提供统一的「先正常 DNS，连不上再 DoH + 直连」HTTP 调用
# 入口：http_request(method, url, *, headers, body, timeout) -> (status, data, how) / resolve_ips(host)
# 依赖：requests（必需）、urllib3（可选；缺了就没有兜底，退化成普通 requests）
# 不负责：改 hosts、判断版本、解析仓库内容、写任何文件
# 验证：python backend/update_check.py --self-test
# 被调用：backend/updater.py、tools/publish.py
# 索引：docs/MODULE_MAP.md §1「直连兜底」

"""有些机器被 hosts 把 github.com / api.github.com / raw.githubusercontent.com 指到 127.0.0.1，
正常 DNS 必然连不上（SSLError / 连接被拒）。这里用公共 DoH（阿里、腾讯）解析出真实 IP，
再用 SNI + Host 头直连：TLS 证书仍按**真实域名**校验，安全性不降级。

只在本机网络确实连不上时才走兜底，正常能连的机器完全不受影响。
"""

from __future__ import annotations

from urllib.parse import urlsplit

import requests

try:  # urllib3 随 requests 一起装；单独 try 是为了缺它时还能当普通 requests 用
    import urllib3
except Exception:  # pragma: no cover - 环境缺库时的退化路径
    urllib3 = None

DOH_URLS = (
    "https://dns.alidns.com/resolve",
    "https://doh.pub/dns-query",
)
DOH_TIMEOUT = 8
_CACHE = {}


def resolve_ips(host: str, timeout: int = DOH_TIMEOUT) -> list:
    """用公共 DoH 解析 A 记录；解析不到返回空列表（不抛异常）。"""
    host = (host or "").strip()
    if not host:
        return []
    if host in _CACHE:
        return _CACHE[host]
    ips = []
    for url in DOH_URLS:
        try:
            resp = requests.get(url, params={"name": host, "type": "A"},
                                headers={"accept": "application/dns-json"}, timeout=timeout)
            for item in (resp.json().get("Answer") or []):
                if item.get("type") == 1 and item.get("data"):
                    ips.append(str(item["data"]))
        except Exception:
            continue
        if ips:
            break
    ips = list(dict.fromkeys(ips))
    _CACHE[host] = ips
    return ips


def http_request(method: str, url: str, *, headers: dict = None, body: bytes = None,
                 timeout: int = 12):
    """返回 (status, data, how)：how 为 "dns" 表示正常走的，为 "doh+ip" 表示走了直连兜底。"""
    try:
        resp = requests.request(method, url, headers=headers, data=body, timeout=timeout)
        return resp.status_code, resp.content, "dns"
    except requests.RequestException as first_error:
        if urllib3 is None:
            raise
        parts = urlsplit(url)
        host = parts.hostname or ""
        last_error = first_error
        for ip in resolve_ips(host):
            try:
                pool = urllib3.HTTPSConnectionPool(
                    ip, server_hostname=host, assert_hostname=host,
                    cert_reqs="CERT_REQUIRED", timeout=timeout, retries=False,
                )
                send_headers = dict(headers or {})
                send_headers.setdefault("Host", host)
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                resp = pool.request(method, path, body=body, headers=send_headers)
                return resp.status, resp.data, "doh+ip"
            except Exception as exc:  # 换下一个 IP 再试
                last_error = exc
        raise last_error
