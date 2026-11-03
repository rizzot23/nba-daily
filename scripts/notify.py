#!/usr/bin/env python3
"""把当天战报摘要推到微信（Server 酱 / PushPlus 通用 webhook）。

**只做提醒，不碰公众号任何接口。** 原因是权限：个人未认证订阅号在
2025 年 7 月被回收了 freepublish/submit 和 message/mass/send（返回 48001），
所以「自动发布」这条路根本不存在。最后一步「群发」必须人工点 + 管理员扫码。

这一层要解决的只有一件事：别让人忘了去点。

用法：
    SC_KEY=xxxx python scripts/notify.py

环境变量：
    SC_KEY        Server 酱 SendKey。没配就静默跳过，不影响主流程。
    REPORT_URL    战报地址。不填则按 GITHUB_REPOSITORY 推 GitHub Pages 地址。

零依赖，只用标准库。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LATEST = BASE_DIR.parent / "docs" / "latest.json"


def cn_date(iso):
    """2026-11-02 -> 11月2日"""
    try:
        _, m, d = iso.split("-")
        return f"{int(m)}月{int(d)}日"
    except Exception:
        return iso


def pages_url():
    """没显式给地址时，按仓库名推 GitHub Pages 的路径。

    仓库叫 <user>.github.io 时是根域；其他仓库名会带一级子路径。
    """
    explicit = os.environ.get("REPORT_URL", "").strip()
    if explicit:
        return explicit

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo or "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io/report.html"
    return f"https://{owner}.github.io/{name}/report.html"


def build_message(d):
    """返回 (标题, 正文 markdown)。内容全部取自 latest.json，不额外编造。"""
    day = cn_date(d.get("game_date", ""))
    n = d.get("total_games") or 0
    if n:
        title = f"去球吧 · {day} {n} 场"
    else:
        title = f"去球吧 · {day} 无比赛"

    lines = []
    if d.get("lead"):
        lines.append(d["lead"])
        lines.append("")

    # 四类标签，只列当天真正打上的那几个
    tagged = [g for g in (d.get("games") or []) if g.get("label")]
    if tagged:
        for g in tagged:
            lines.append(
                f"- **{g['label']}**：{g['away']} {g['away_score']}-{g['home_score']} {g['home']}"
            )
        lines.append("")

    t = d.get("tomorrow") or {}
    if t.get("status") == "play" and t.get("pick"):
        p = t["pick"]
        lines.append(f"**明日焦点** {p.get('away')} @ {p.get('home')}")
        lines.append(f"{p.get('bj_date')} {p.get('bj_time')}")
    elif t.get("status") == "idle":
        lines.append(f"**明日休战** 下一比赛日 {t.get('date_cn')}")
    lines.append("")

    url = pages_url()
    if url:
        lines.append(f"[打开战报 →]({url})")

    return title, "\n".join(lines).strip()


def send(sckey, title, desp):
    """Server 酱 Turbo 接口。失败只打印，不抛。"""
    url = f"https://sctapi.ftqq.com/{sckey}.send"
    body = urllib.parse.urlencode({"title": title, "desp": desp}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "nba-daily-report/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode("utf-8") or "{}")
    # Server 酱成功返回 {"code": 0, ...}，失败常见 code 40001(Key 错) / 40032(超频)
    if payload.get("code") != 0:
        raise RuntimeError(f"推送失败：{payload}")
    return payload


def main():
    sckey = os.environ.get("SC_KEY", "").strip()
    if not sckey:
        print("未配置 SC_KEY，跳过微信提醒")
        return 0

    if not LATEST.exists():
        print(f"没有 {LATEST}，跳过微信提醒")
        return 0

    d = json.loads(LATEST.read_text(encoding="utf-8"))
    title, desp = build_message(d)
    print(f"标题：{title}")
    print("正文：")
    print(desp)

    try:
        send(sckey, title, desp)
        print("微信提醒已发出")
    except urllib.error.HTTPError as e:
        print(f"推送失败：HTTP {e.code}")
        return 1
    except Exception as e:
        print(f"推送失败：{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
