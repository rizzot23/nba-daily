#!/usr/bin/env python3
"""把 latest.json 转成头条号用的选题稿（docs/toutiao.md）。

为什么单独出一份：头条是算法推荐，每篇都要重新争推荐位。平台运营规则里
明确列了「批量发布同质化内容、模板化内容无个人观点」是降权项 —— 同一套
战报换个数据发过去，在公众号是专业感，在头条就是低质重复。所以这边不做
全量战报，只出：1 篇主推 + 2 个备选 + 几条微头条，每篇只讲一个点。

所有句子都必须能从 latest.json 的字段推出来，不编因果、不加形容词。

用法：
    python scripts/export_toutiao.py
产物：
    docs/toutiao.md
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR.parent / "docs"
LATEST = OUT_DIR / "latest.json"
TARGET = OUT_DIR / "toutiao.md"
PLAYERS_FILE = BASE_DIR / "players_zh.json"

TITLE_LIMIT = 30          # 头条图文标题上限，按字符算


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


PLAYERS = {str(k).lower(): v for k, v in (load_json(PLAYERS_FILE, {}) or {}).items()}


# ------------------------------------------------------------------ 小工具

def sec_text(s):
    """7.3 -> '7.3'，10.0 -> '10'。和正文里的写法保持一致。"""
    if s is None:
        return ""
    s = round(float(s), 1)
    if s <= 0.5:
        return "0"
    return str(int(s)) if abs(s - int(s)) < 1e-9 else f"{s:g}"


def sp(a, b):
    """拼接时补空格。中文和中文之间不加，碰到英文/数字加一个 ——
    否则会出现「Fears投进反超球」这种挤在一起的写法。"""
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return a + b
    return f"{a} {b}" if (a[-1].isascii() or b[0].isascii()) else a + b


def player_cn(name):
    """英文全名转中文。没收录就退到姓氏 —— 单个姓氏比整串英文好读。"""
    if not name:
        return ""
    key = " ".join(str(name).lower().replace(".", " ").split())
    if key in PLAYERS:
        return PLAYERS[key]
    return str(name).split()[-1]


def winner(g):
    return g["away"] if g["away_score"] > g["home_score"] else g["home"]


def loser(g):
    return g["home"] if g["away_score"] > g["home_score"] else g["away"]


def margin(g):
    return abs(g["away_score"] - g["home_score"])


def vs(g):
    return f'{g["away"]} {g["away_score"]}-{g["home_score"]} {g["home"]}'


def tidy(text, limit=TITLE_LIMIT):
    """标题塞进 30 字。先去掉多余空格，还超就去掉全部空格，再超就放弃这条。"""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    text = text.replace(" ", "")
    return text if len(text) <= limit else None


def kind_of(g):
    dr = g.get("drama") or {}
    if dr.get("clutch"):
        return "clutch"
    if (dr.get("comeback") or 0) >= 12:
        return "comeback"
    if margin(g) <= 8 or (dr.get("lead_changes") or 0) >= 8:
        return "close"
    return "blowout"


KIND_CN = {"clutch": "绝杀", "comeback": "逆转", "close": "胶着", "blowout": "大胜"}

ADVICE = {
    "clutch": "别从跳球写起。开头两句就把那一球给出去，第二段再倒回去讲：反超之前是被谁追平的、"
              "教练最后一攻布置给了谁。读者是为那一球点进来的，铺垫越短越好。",
    "comeback": "先给结果，再按节拆。哪一节开始追、追到几分、最后一节靠什么收尾 —— 三段就够，"
                "不要每节都写，没人关心第二节。",
    "close": "别写成流水账。只写第四节最后三分钟，一回合一回合地过，前面三节压成一句话。",
    "blowout": "这种比分头条不吃推荐。除非有别的钩子（球星爆了、破纪录、主力伤退），"
               "否则别选它，宁可今天只发一条微头条。",
}


# ------------------------------------------------------------------ 选题

def score_game(g, focus):
    """选题分。绝杀压倒一切，其次是逆转和胶着，最后看焦点球星爆没爆。"""
    dr = g.get("drama") or {}
    s = 0.0
    if dr.get("clutch"):
        s += 100
    if g.get("overtimes"):
        s += 35
    m = margin(g)
    if m <= 3:
        s += 45
    elif m <= 5:
        s += 30
    s += min(dr.get("lead_changes") or 0, 20) * 2.5
    s += min(dr.get("comeback") or 0, 20) * 2.5
    if g.get("label"):
        s += 20
    teams = (g["away"], g["home"])
    for f in focus or []:
        if f.get("state") != "played" or f.get("team") not in teams:
            continue
        pts = int(f.get("pts") or 0)
        s += 70 if pts >= 30 else 45 if pts >= 25 else 25 if pts >= 20 else 0
    return s


def pick_topics(games, focus, headline, limit=3):
    """主推固定是当天头条那场，剩下的按分数补。"""
    if not games:
        return []
    head = None
    for g in games:
        if vs(g) == (headline or ""):
            head = g
            break
    rest = sorted(
        [g for g in games if g is not head],
        key=lambda g: score_game(g, focus),
        reverse=True,
    )
    out = ([head] if head else []) + rest
    return out[:limit]


def facts_of(g):
    """可复核的数据点。每条都要能对着 ESPN 的 boxscore 验。"""
    dr = g.get("drama") or {}
    out = [f'比分：{vs(g)}，{winner(g)}赢 {margin(g)} 分']
    if g.get("overtimes"):
        out.append(f'打了 {g["overtimes"]} 个加时')
    cl = dr.get("clutch")
    if cl:
        who = player_cn(cl.get("player_en"))
        when = "加时" if (cl.get("period") or 0) > 4 else "第四节"
        out.append(f'{when}剩 {sec_text(cl.get("clock"))} 秒，{sp(who, "投进反超球")}，'
                   f'两队此后都没再得分')
    if dr.get("lead_changes"):
        out.append(f'全场交替领先 {dr["lead_changes"]} 次、打平 {dr.get("ties") or 0} 次')
    if (dr.get("comeback") or 0) >= 8:
        out.append(f'{winner(g)}最多落后 {dr["comeback"]} 分')
    sec = dr.get("close_seconds_q4") or 0
    if sec >= 120:
        span = "第四节和加时" if g.get("overtimes") else "第四节"
        out.append(f'{span}里分差没超过 5 分的净时间共 {sec // 60} 分 {sec % 60} 秒')
    if g.get("series"):
        out.append(g["series"])
    return out


def titles_of(g):
    """两个标题，陈述句 + 具体数字。不用「震惊」「万万没想到」，也不堆感叹号。"""
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    w, l, m = winner(g), loser(g), margin(g)
    cb = dr.get("comeback") or 0
    out = []
    if cl:
        sec = sec_text(cl.get("clock"))
        when = "加时" if (cl.get("period") or 0) > 4 else "末节"
        out.append(tidy(f'{when}剩 {sec} 秒反超，{vs(g)}'))
        out.append(tidy(f'{dr.get("lead_changes") or 0} 次交替领先，胜负定在最后 {sec} 秒'))
    elif cb >= 12:
        out.append(tidy(f'{w}落后 {cb} 分，最后赢 {m} 分'))
        out.append(tidy(f'{l}领先 {cb} 分，被{w}翻了'))
    elif (dr.get("lead_changes") or 0) >= 8:
        out.append(tidy(f'{dr["lead_changes"]} 次交替领先，{vs(g)}'))
        out.append(tidy(f'{w}只赢 {m} 分，这场从头缠到尾'))
    elif m >= 15:
        out.append(tidy(f'{vs(g)}，{w}赢 {m} 分'))
        out.append(tidy(f'{w}{m} 分大胜{l}'))
    else:
        out.append(tidy(f'{vs(g)}，{w}赢 {m} 分'))
        out.append(tidy(f'{w}只赢 {m} 分，{l}咬到最后'))
    return [t for t in out if t]


def why_of(g):
    """一句话说清为什么值得写。"""
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    if cl:
        when = "加时" if (cl.get("period") or 0) > 4 else "末节"
        return (f'{when}剩 {sec_text(cl.get("clock"))} 秒才反超，'
                f'全场 {dr.get("lead_changes") or 0} 次交替领先。')
    if (dr.get("comeback") or 0) >= 12:
        return f'{winner(g)}落后 {dr["comeback"]} 分翻盘，赢 {margin(g)} 分。'
    if g.get("series"):
        return f'{g["series"]}。'
    if (dr.get("lead_changes") or 0) >= 8:
        return f'{dr["lead_changes"]} 次交替领先，最后只差 {margin(g)} 分。'
    return f'{winner(g)}赢 {margin(g)} 分。'


# ------------------------------------------------------------------ 微头条

def micro_main(g):
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    w, m = winner(g), margin(g)
    if g.get("overtimes"):
        head = f'{vs(g)}，打了 {g["overtimes"]} 个加时才分出胜负。'
    elif m <= 3:
        head = f'{vs(g)}，最后只差 {m} 分。'
    else:
        head = f'{vs(g)}，{w}赢 {m} 分。'
    lines = [head]
    if cl:
        who = player_cn(cl.get("player_en"))
        when = "加时" if (cl.get("period") or 0) > 4 else "末节"
        lines.append(f'{when}剩 {sec_text(cl.get("clock"))} 秒，{sp(who, "投进反超球")}，此后两边都没再得分。')
    if dr.get("lead_changes"):
        lines.append(f'全场交替领先 {dr["lead_changes"]} 次、打平 {dr.get("ties") or 0} 次，'
                     f'谁也没能真正甩开对手。')
    elif (dr.get("comeback") or 0) >= 12:
        lines.append(f'{w}一度落后 {dr["comeback"]} 分。')
    return "\n".join(lines)


def micro_comeback(g):
    dr = g.get("drama") or {}
    return (f'{vs(g)}。\n'
            f'最多落后 {dr.get("comeback") or 0} 分，最后赢了 {margin(g)} 分。')


def micro_star(f, games=None):
    """焦点球星的单条。数据是死的，别替他总结性格。
    能配上比分就配比分 —— 只写「XX 34 分」太干，微头条需要一点上下文。"""
    line = f'{f["cn"]} {f.get("pts") or 0} 分'
    if f.get("reb") and str(f.get("reb")) != "0":
        line += f' {f["reb"]} 板'
    if f.get("ast") and str(f.get("ast")) != "0":
        line += f' {f["ast"]} 助'
    team = f.get("team") or ""
    for g in games or []:
        if team and team in (g["away"], g["home"]):
            return line + f'，{vs(g)}。'
    opp, res = f.get("opp") or "", f.get("result") or ""
    return line + (f'，{team}{res}{opp}。' if team and opp else "。")


def micro_best(b):
    if not b:
        return ""
    kind = b.get("kind")
    who = player_cn(b.get("player"))
    when = "加时" if (b.get("period") or 0) > 4 else f'第 {b.get("period") or 0} 节'
    if kind == "clutch":
        return (f'{who}在{when}剩 {sec_text(b.get("clock_sec"))} 秒投进反超球，'
                f'{b.get("game")}，这球直接分出了胜负。')
    if kind == "three" and b.get("dist_ft"):
        return f'{who}在{when}投进一记 {b["dist_ft"]} 英尺三分，{b.get("game")}。'
    cn = {"dunk": "扣篮", "alley-oop": "空中接力扣篮", "block": "盖帽", "three": "三分"}.get(kind, "好球")
    return f'{who}在{when}送出一次{cn}，{b.get("game")}。'


def _bj(p):
    return " ".join(x for x in (p.get("bj_date") or "", p.get("bj_time") or "") if x)


def micro_tomorrow(t):
    """「明天」是按美国比赛日算的，但读者在北京。两边日期都写出来，
    否则出现「11月4日的比赛，北京时间 11月5日」会把人绕晕。"""
    if not t:
        return ""
    p = t.get("pick") or {}
    if t.get("status") == "play" and p:
        line = (f'明天 {t.get("total") or 0} 场。最值得定闹钟的是'
                f'{p.get("away")} @ {p.get("home")}')
        bj = _bj(p)
        return line + (f'，北京时间 {bj}。' if bj else "。")
    if t.get("status") == "idle":
        reason = f' —— {t["reason"]}' if t.get("reason") else ""
        nxt = ""
        if p:
            nxt = (f'下一个比赛日是美国时间 {t.get("date_cn") or ""}：'
                   f'{p.get("away")} @ {p.get("home")}')
            bj = _bj(p)
            nxt += (f'，北京时间 {bj}。' if bj else "。")
        return f'明天全联盟没有比赛{reason}。{nxt}'.strip()
    return "接下来两周都没有比赛。"


# ------------------------------------------------------------------ 渲染

def render_topic(idx, g, title_prefix):
    lines = [f'## {title_prefix}｜{vs(g)}' + (f'（{g["overtimes"]} 个加时）' if g.get("overtimes") else "")]
    lines.append("")
    lines.append(f'**为什么是这场**：{why_of(g)}')
    lines.append("")
    lines.append("**能用的数据**（都能在 ESPN 上复核，别改数）")
    for f in facts_of(g):
        lines.append(f"- {f}")
    lines.append("")
    titles = titles_of(g)
    if titles:
        lines.append(f"**标题**（头条限 {TITLE_LIMIT} 字内，可直接用）")
        for i, t in enumerate(titles, 1):
            lines.append(f"{i}. {t}")
        lines.append("")
    lines.append(f'**怎么写**：{ADVICE[kind_of(g)]}')
    lines.append("")
    return "\n".join(lines)


def render(d):
    games = d.get("games") or []
    focus = d.get("focus") or []
    date_cn = d.get("game_date") or ""
    y, mo, dd = (str(date_cn).split("-") + ["", "", ""])[:3]
    pretty = f"{int(y)}年{int(mo)}月{int(dd)}日" if y and mo and dd else date_cn
    postseason = "季后赛" if d.get("postseason") else "常规赛"
    n = len(games)

    out = [f"# 头条素材 · {pretty}（美国时间）", ""]
    if n == 0:
        out.append("今天没有比赛，这一期不用发长文。")
        out.append("")
        tmr = micro_tomorrow(d.get("tomorrow"))
        if tmr:
            out.append("可以发一条微头条，把明天的看点放出去：")
            out.append("")
            out.append(tmr)
            out.append("")
    else:
        head = f"今天{postseason} {n} 场全部打完。" if n > 1 else f"今天只有 1 场{postseason}。"
        out.append(f"{head}下面按「主推 → 备选 → 微头条 → 明日」排，")
        out.append("每段都能整段复制。数字别改；标题可以换成自己的语气，但别加「震惊」「史上」这类词，")
        out.append("头条的标题党判定是直接扣信用分的。")
        out.append("")
        out.append("---")
        out.append("")

        topics = pick_topics(games, focus, d.get("headline"))
        for i, g in enumerate(topics):
            out.append(render_topic(i, g, "主推" if i == 0 else f"备选 {i}"))
            out.append("---")
            out.append("")

        out.append("## 微头条（一条一个点，挑几条发就行，别一次全扔）")
        out.append("")
        shorts = []
        main_g = topics[0] if topics else None
        if main_g:
            shorts.append(("今天这场", micro_main(main_g)))
        cb = [
            g for g in games
            if g is not main_g and (g.get("drama") or {}).get("comeback", 0) >= 12
        ]
        if cb:
            shorts.append(("翻盘", micro_comeback(cb[0])))
        hot = sorted(
            [f for f in focus if f.get("state") == "played"],
            key=lambda f: int(f.get("pts") or 0), reverse=True,
        )
        for f in hot[:2]:
            shorts.append((f.get("cn") or "", micro_star(f, games)))
        b = d.get("best_action")
        # 最佳一球如果就是主推那场的绝杀，前面已经讲过，别重复
        if b and not (main_g and b.get("kind") == "clutch" and b.get("game") == vs(main_g)):
            shorts.append(("最佳一球", micro_best(b)))
        tmr = micro_tomorrow(d.get("tomorrow"))
        if tmr:
            shorts.append(("明日", tmr))

        for i, (tag, text) in enumerate(shorts, 1):
            body = "\n".join(text.split("\n"))
            out.append(f"### {i}｜{tag}（{len(body)} 字）")
            out.append("")
            out.append(body)
            out.append("")

        out.append("---")
        out.append("")
        out.append("## 发文前自查")
        out.append("")
        out.append("- 标题 ≤ 30 字，正文第一段别超过三行")
        out.append("- 配图只用 1 张（`docs/cover.png`），头条不认外链图，要手动上传")
        out.append("- 别把公众号那篇原样搬过来，两边都发会被判「站外重复」")
        out.append("- 微头条一天别超过 5 条，多了会限流")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def main():
    if not LATEST.exists():
        print("没有 latest.json，跳过头条素材")
        return 0
    d = load_json(LATEST, {})
    if not d:
        print("latest.json 读不出来，跳过头条素材")
        return 0
    TARGET.write_text(render(d), encoding="utf-8")
    print(f"头条素材已生成：{TARGET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"头条素材生成失败：{exc}", file=sys.stderr)
        sys.exit(1)
