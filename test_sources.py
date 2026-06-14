"""一键测试所有源的 RSS URL 可访问性。"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Windows GBK 终端兼容
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import feedparser
import requests

CONFIG_PATH = Path(__file__).parent / ".github" / "cache" / "source_config.json"
USER_AGENT = "SemiconductorNewsBot/1.0"
TIMEOUT = 20

def test_source(src: dict) -> dict:
    sid = src["id"]
    name = src["name"]
    url = src.get("url", "")
    result = {"id": sid, "name": name, "url": url, "status": "unknown", "entries": 0, "error": ""}

    if not url:
        result["status"] = "no_url"
        result["error"] = "未配置 URL"
        return result

    # 去掉 ! 标记
    clean_url = url.rstrip("!")

    if src.get("type") == "api":
        # API 类型用 requests
        try:
            resp = requests.get(clean_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            if resp.ok:
                result["status"] = "ok"
                result["entries"] = "N/A (API)"
            else:
                result["status"] = "http_error"
                result["error"] = f"HTTP {resp.status_code}"
        except requests.exceptions.Timeout:
            result["status"] = "timeout"
            result["error"] = "请求超时"
        except requests.exceptions.ConnectionError as e:
            result["status"] = "connection_error"
            result["error"] = str(e)[:150]
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)[:150]
    else:
        # RSS 类型用 feedparser
        try:
            feed = feedparser.parse(
                clean_url,
                agent=USER_AGENT,
                request_headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            )

            if feed.bozo and not feed.entries:
                bozo_msg = str(getattr(feed, "bozo_exception", "parse error"))
                result["status"] = "parse_error"
                result["error"] = bozo_msg[:200]
            elif feed.entries:
                result["status"] = "ok"
                result["entries"] = len(feed.entries)
            elif feed.bozo:
                # 有 bozo 但有 entries，可能只是格式小问题
                result["status"] = "ok (bozo)"
                result["entries"] = len(feed.entries)
                result["error"] = str(getattr(feed, "bozo_exception", ""))[:150]
            else:
                result["status"] = "empty"
                result["error"] = "解析成功但无条目（可能非 RSS 格式）"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)[:200]

    return result


def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = cfg["sources"]

    print(f"测试 {len(sources)} 个源，并发 8 线程，超时 {TIMEOUT}s\n")

    results = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(test_source, s): s["id"] for s in sources}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            results.append(r)
            icon = "OK" if r["status"].startswith("ok") else "FAIL"
            detail = f"({r['entries']} 条目)" if isinstance(r["entries"], int) and r["entries"] > 0 else ""
            print(f"[{i:2d}/{len(sources)}] {icon} {r['id']:30s} {r['url'][:80]}")
            if r["error"]:
                print(f"       └─ {r['error'][:120]}")

    # 分类汇总
    results.sort(key=lambda r: (-(r["status"].startswith("ok")), r["id"]))

    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)

    ok = [r for r in results if r["status"].startswith("ok")]
    fail = [r for r in results if not r["status"].startswith("ok")]

    print(f"\n通过: {len(ok)} 个")
    for r in ok:
        print(f"  OK  {r['id']:30s} {r['entries']} 条")

    print(f"\n失败: {len(fail)} 个")
    for r in fail:
        print(f"  {r['status']:20s} {r['id']:30s} {r['error'][:100]}")

    # 输出修复建议
    print("\n" + "=" * 70)
    print("需要手动修复的源及其已知信息")
    print("=" * 70)
    for r in fail:
        name = r["name"]
        sid = r["id"]
        if r["status"] == "http_error":
            print(f"  {sid}: 返回 HTTP 错误 — 尝试浏览器打开 {r['url']} 确认是否可访问")
        elif r["status"] == "parse_error":
            print(f"  {sid}: 不是合法 RSS/Atom — 访问 {r['url']} 查看页面是否有 RSS 链接")
        elif r["status"] == "empty":
            print(f"  {sid}: 可能是普通 HTML 页面而非 RSS — 在 {name} 网站查找 RSS 图标或 /feed 路径")
        elif r["status"] == "connection_error":
            print(f"  {sid}: 连接失败 — 可能需要翻墙或 URL 已失效")
        elif r["status"] == "no_url":
            print(f"  {sid}: 未配置 URL — 需手动查找 {name} 的 RSS 源")


if __name__ == "__main__":
    main()
