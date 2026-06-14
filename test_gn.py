"""测试 Google News RSS 可访问性（通过代理 / 直连）"""
import feedparser
import os

# 如果本地有代理
proxies = {}
if os.environ.get("HTTP_PROXY"):
    proxies["http"] = os.environ["HTTP_PROXY"]
if os.environ.get("HTTPS_PROXY"):
    proxies["https"] = os.environ["HTTPS_PROXY"]

url = "https://news.google.com/rss/search?q=TSMC+semiconductor+when:7d&hl=en-US&gl=US&ceid=US:en"
print(f"测试 URL: {url[:100]}...")
print(f"代理: {proxies if proxies else '无'}")

try:
    import requests
    if proxies:
        resp = requests.get(url, timeout=15, proxies=proxies, headers={"User-Agent": "TestBot/1.0"})
    else:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "TestBot/1.0"})
    print(f"HTTP {resp.status_code}, 内容长度 {len(resp.text)}")
    print(f"前 200 字符: {resp.text[:200]}")
except Exception as e:
    print(f"连接失败: {e}")
    print("Google News 在墙内无法直连 — 需要代理或在 GH Actions 中运行")
