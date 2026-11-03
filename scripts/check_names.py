#!/usr/bin/env python3
"""查当天比赛的球员里，还有谁没进 players_zh.json。

为什么需要这个：NBA 每个赛季有 60 个新秀进来、还有一堆双向合同球员轮着上，
手写译名表永远追不上名单。这个脚本不自动翻译（机翻的球员名会把「约基奇」
写成「乔基奇」），只负责把缺的人列出来，人补。

用法：
    python scripts/check_names.py                 # 查昨天（按北京时间推比赛日）
    python scripts/check_names.py 2026-11-02      # 查指定比赛日
    python scripts/check_names.py --all           # 列出当天全部出场球员，不只每队前三

输出里的「待补模板」整段粘进 players_zh.json，填上中文名就行 —— key 已经按
ESPN 的写法归一过了，带不带句点都能匹配。
"""

import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PLAYERS_FILE = BASE_DIR / "players_zh.json"
BJ_TZ = timezone(timedelta(hours=8))

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"


def nk(name):
    """查表 key。必须和 fetch_nba.normalize_name 一致，否则同一份表在两个脚本里命中率不同。"""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace(".", "")
    return " ".join(s.lower().split())


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def resolve_date(argv):
    if argv and re.fullmatch(r"\d{4}-\d{2}-\d{2}", argv[0]):
        return argv[0]
    override = os.environ.get("REPORT_GAME_DATE", "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", override):
        return override
    # 和 fetch_nba 一致：北京时间今天的战报，对应美国的「昨天」比赛日
    return (datetime.now(BJ_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def top_scorers(block, limit):
    """每队取 PTS 最高的 N 人。limit=0 表示全要。"""
    out = []
    for group in block.get("statistics") or []:
        labels = [str(x).upper() for x in (group.get("labels") or [])]
        if "PTS" not in labels:
            continue
        i = labels.index("PTS")
        rows = []
        for a in group.get("athletes") or []:
            st = a.get("stats") or []
            name = ((a.get("athlete") or {}).get("displayName")) or ""
            if not name:
                continue
            try:
                pts = int(str(st[i]).split("-")[0])
            except (IndexError, TypeError, ValueError):
                pts = -1
            rows.append((pts, name))
        rows.sort(reverse=True)
        out.extend(n for _, n in (rows if limit <= 0 else rows[:limit]))
    return out


def main(argv):
    limit = 0 if "--all" in argv else 3
    date = resolve_date([a for a in argv if not a.startswith("--")])
    compact = date.replace("-", "")

    try:
        sb = get(f"{API}/scoreboard?dates={compact}")
    except Exception as e:
        print(f"取不到 {date} 的记分板：{e}")
        return 1

    events = sb.get("events") or []
    if not events:
        print(f"{date}（美国时间）没有比赛")
        return 0

    seen = {}
    for ev in events:
        try:
            s = get(f"{API}/summary?event={ev['id']}")
        except Exception as e:
            print(f"  跳过 {ev.get('id')}：{e}")
            continue
        for blk in (s.get("boxscore") or {}).get("players", []):
            abbr = (blk.get("team") or {}).get("abbreviation") or "?"
            for name in top_scorers(blk, limit):
                seen.setdefault(name, abbr)

    have = {nk(k) for k in json.loads(PLAYERS_FILE.read_text(encoding="utf-8")).keys()}
    missing = sorted((n for n in seen if nk(n) not in have), key=lambda x: x.split()[-1])

    scope = "全部出场球员" if limit <= 0 else "每队得分前三"
    print(f"{date}（美国时间）{scope} {len(seen)} 人，已收录 {len(seen) - len(missing)} 人，缺 {len(missing)} 人")
    if not missing:
        print("名单齐了，不用补。")
        return 0

    print("\n缺译名的：")
    for i in range(0, len(missing), 3):
        print("  " + "   ".join(f"{n}（{seen[n]}）" for n in missing[i:i + 3]))

    print("\n待补模板（填中文名后粘进 scripts/players_zh.json）：")
    print("{")
    for n in missing:
        print(f'  "{nk(n)}": "",')
    print("}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
