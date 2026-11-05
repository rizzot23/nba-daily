#!/usr/bin/env python3
"""今日主打：从当天 N 场里挑一场，出成一篇能直接动手写的内容。

**一份内容，两个平台：**

- 公众号次条 —— 读者刚在头条看完完整战报，这条要「深读一场」，可以长、可以绕回去
- 头条号 —— 算法推荐给陌生人，标题 30 字、钩子前置、800–1200 字

为什么两边都只讲一场：公众号主条已经是 15 场全展开，次条再全展开就是自己跟自己重复；
头条更严格，平台运营规则明确把「批量发布同质化内容、模板化内容无个人观点」列为降权项，
同一套战报换个数据发过去，在公众号是专业感，在头条就是低质重复。

所有句子都必须能从 latest.json 的字段推出来，不编因果、不加形容词。

用法：
    python scripts/export_feature.py
产物：
    docs/feature.md     给人看的写作稿，整段可复制
    docs/feature.json   给 Actions 摘要和微信提醒用的一行摘要
"""

import json
import sys
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR.parent / "docs"
LATEST = OUT_DIR / "latest.json"
TARGET = OUT_DIR / "feature.md"
BRIEF = OUT_DIR / "feature.json"
PLAYERS_FILE = BASE_DIR / "players_zh.json"

BRAND = "去球吧"
TITLE_LIMIT = 30          # 头条图文标题上限，按字符算


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _nk(name):
    """球员名的查表 key。必须和 fetch_nba.normalize_name 保持同一套规则 ——
    两个脚本各自读同一份 players_zh.json，规则一旦分叉，同一份表在正文里能命中、
    在写作稿里却查不到。"""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace(".", "")
    return " ".join(s.lower().split())


PLAYERS = {_nk(k): v for k, v in (load_json(PLAYERS_FILE, {}) or {}).items()}


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
    hit = PLAYERS.get(_nk(name))
    if hit:
        return hit
    parts = [p for p in str(name).split() if p not in ("Jr.", "Sr.", "II", "III", "IV")]
    return parts[-1] if parts else str(name)


def winner(g):
    return g["away"] if g["away_score"] > g["home_score"] else g["home"]


def loser(g):
    return g["home"] if g["away_score"] > g["home_score"] else g["away"]


def margin(g):
    return abs(g["away_score"] - g["home_score"])


def vs(g):
    return f'{g["away"]} {g["away_score"]}-{g["home_score"]} {g["home"]}'


def when_of(cl):
    return "加时" if (cl.get("period") or 0) > 4 else "末节"


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


def pick_feature(games, focus, headline=None):
    """当天只留一场：谁最热闹谁上。

    headline 是简报里的「今日最狠的一场」，只在跟最高分几乎打平的时候优先用它 ——
    主条导语提过它，次条接着写同一场，前后不会打架。但如果当天另有一场绝杀，
    绝杀那场的选题分要高出 100 分，那就该换人，不能为了对齐导语错过真正的好球。
    """
    if not games:
        return None
    best = max(games, key=lambda g: score_game(g, focus))
    if headline:
        top = score_game(best, focus)
        for g in games:
            if vs(g) == headline and score_game(g, focus) >= top - 10:
                return g
    return best


# ------------------------------------------------------------------ 文本

def titles_toutiao(g):
    """头条标题：陈述句 + 具体数字，30 字硬限。不用「震惊」「万万没想到」。"""
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    w, l, m = winner(g), loser(g), margin(g)
    cb = dr.get("comeback") or 0
    out = []
    if cl:
        sec = sec_text(cl.get("clock"))
        when = when_of(cl)
        out.append(tidy(f'{when}剩 {sec} 秒反超，{vs(g)}'))
        out.append(tidy(f'{vs(g)}，胜负定在最后 {sec} 秒'))
        # 既有两位数逆转又有绝杀时，逆转比「N 次交替领先」有信息量。
        # 11-04 热火落后 20 分翻盘，第三条原写「8 次交替领先」，把最好的素材丢了
        if cb >= 12:
            out.append(tidy(f'{w}落后 {cb} 分，{when}最后 {sec} 秒翻盘'))
        else:
            out.append(tidy(f'{dr.get("lead_changes") or 0} 次交替领先，最后 {sec} 秒才分出'))
    elif cb >= 12:
        out.append(tidy(f'{w}落后 {cb} 分，最后赢 {m} 分'))
        out.append(tidy(f'{l}领先 {cb} 分，被{w}翻了'))
    elif (dr.get("lead_changes") or 0) >= 8:
        out.append(tidy(f'{dr["lead_changes"]} 次交替领先，{vs(g)}'))
        out.append(tidy(f'{w}只赢 {m} 分，这场从头缠到尾'))
    else:
        out.append(tidy(f'{vs(g)}，{w}赢 {m} 分'))
        out.append(tidy(sp(sp(w, m) + ' 分击败', l)))
    return [t for t in out if t]


def titles_wechat(g):
    """公众号次条标题：可以长一点，但信息流只露前 20 字，钩子必须在前半句。
    和头条那组刻意错开措辞，两边都发才不像同一篇。

    注意绝杀有两种：赢的那队本来落后（逆转式绝杀），或者两队打平后一球定胜负。
    写死「XX 领先了一整晚」会出现「鹈鹕领先了一整晚，输在最后 7.3 秒」这种
    赢家被写成输家的句子，所以分情况。
    """
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    w, l, m = winner(g), loser(g), margin(g)
    cb = dr.get("comeback") or 0
    out = []
    if cl:
        sec = sec_text(cl.get("clock"))
        when = when_of(cl)
        who = player_cn(cl.get("player_en")) or "他"
        before = cl.get("before") or 0
        if before < 0:
            # -before 只是最后一回合的分差。全场落后过两位数时写「落后 2 分」，
            # 读者会以为这是场势均力敌的球，把最狠的情节藏掉了
            lead = cb if cb >= 12 else -before
            out.append(f'{w}落后 {lead} 分，最后 {sec} 秒翻了')
            out.append(f'{when}还剩 {sec} 秒，{sp(who, "把球投进")}')
            out.append(f'{l}领先到最后一个回合，然后输了')
        else:
            out.append(f'还剩 {sec} 秒，两队打平，{sp(who, "把球投进")}')
            out.append(f'{l}刚把比分追平，剩下的时间不够了')
            out.append(f'{when}剩 {sec} 秒，这一球分出胜负')
    elif cb >= 12:
        out.append(f'最多落后 {cb} 分，{w}是怎么一场一场追回来的')
        out.append(f'{l}领先 {cb} 分的时候，没人觉得这场还有悬念')
    elif (dr.get("lead_changes") or 0) >= 8:
        out.append(f'领先换了 {dr["lead_changes"]} 次，这场谁也没能甩开谁')
        out.append(f'两队缠了一整场，最后只差 {m} 分')
    else:
        out.append(f'{vs(g)}：{w}赢 {m} 分')
        out.append(f'{w}赢了 {m} 分，这场没留什么悬念')
    return out


def digest(g):
    """公众号摘要，群发时显示在标题下面，硬限 54 字。"""
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    if cl:
        cb = dr.get("comeback") or 0
        sec = sec_text(cl.get("clock"))
        when = when_of(cl)
        # 落后两位数再绝杀，写「从头到尾没松过」是自相矛盾的：
        # 落后 20 分那段就是松了。有逆转就把逆转放前面
        if cb >= 12:
            return tidy(f'落后 {cb} 分翻过来，{when}剩 {sec} 秒才完成反超。',
                        limit=54) or f'{vs(g)}'
        return tidy(
            f'{when}剩 {sec} 秒才反超，'
            f'{dr.get("lead_changes") or 0} 次交替领先，这场从头到尾没松过。',
            limit=54,
        ) or f'{vs(g)}'
    if (dr.get("comeback") or 0) >= 12:
        return tidy(f'{winner(g)}最多落后 {dr["comeback"]} 分，最后赢了 {margin(g)} 分。',
                    limit=54) or f'{vs(g)}'
    return tidy(f'{vs(g)}，{winner(g)}赢 {margin(g)} 分。', limit=54) or f'{vs(g)}'


def opener(g):
    """开场。头条必须前两句就把结果给出去，别从跳球写起。"""
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    if cl:
        who = player_cn(cl.get("player_en")) or "他"
        when = when_of(cl)
        before = cl.get("before") or 0
        gap = f'落后 {-before} 分' if before < 0 else '打平'
        cm = cl.get("margin") or 0
        line = (f'{when}还剩 {sec_text(cl.get("clock"))} 秒，{sp(who, "把球投进")} —— '
                f'{winner(g)}从{gap}变成领先 {cm} 分。')
        # 反超之后胜方常常还能靠罚球涨分，所以不能一律说「比分就停在这里」
        if margin(g) == cm:
            return line + f'终场哨响，比分就停在这里：{vs(g)}。'
        return line + f'终场比分定格在 {vs(g)}。'
    cb = dr.get("comeback") or 0
    if cb >= 12:
        return (f'{vs(g)}。{winner(g)}一度落后 {cb} 分，最后赢了 {margin(g)} 分。'
                f'这不是一节打崩的，是全场一点一点追回来的。')
    if g.get("overtimes"):
        return (f'{vs(g)}，打了 {g["overtimes"]} 个加时。'
                f'常规时间结束的时候，两边谁都没能多进一个球。')
    lc = dr.get("lead_changes") or 0
    if lc >= 8:
        return (f'{vs(g)}。全场交替领先 {lc} 次、打平 {dr.get("ties") or 0} 次，'
                f'分差始终没拉开，最后停在 {margin(g)} 分。')
    return f'{vs(g)}，{winner(g)}赢 {margin(g)} 分。'


def facts_of(g):
    """可复核的数据点。每条都能对着 ESPN 的 boxscore 验。"""
    dr = g.get("drama") or {}
    out = [f'比分：{vs(g)}，{winner(g)}赢 {margin(g)} 分']
    if g.get("overtimes"):
        out.append(f'打了 {g["overtimes"]} 个加时')
    cl = dr.get("clutch")
    if cl:
        who = player_cn(cl.get("player_en"))
        before = cl.get("before") or 0
        gap = f'{winner(g)}落后 {-before} 分' if before < 0 else '两队打平'
        out.append(f'{when_of(cl)}剩 {sec_text(cl.get("clock"))} 秒，{sp(who, "投进反超球")}，'
                   f'这球之前{gap}，投进后领先 {cl.get("margin") or 0} 分')
        # 只保证「对手」之后没得分（反超球取的是败方最后一次得分之后）；
        # 胜方还可能靠罚球继续涨分，别写成两队都没再得分
        cm = cl.get("margin") or 0
        if margin(g) > cm:
            out.append(f'之后{winner(g)}靠罚球把分差拉到 {margin(g)} 分')
        else:
            out.append('这一球之后对手再没得分')
    if dr.get("lead_changes"):
        out.append(f'全场交替领先 {dr["lead_changes"]} 次、打平 {dr.get("ties") or 0} 次')
    if (dr.get("comeback") or 0) >= 8:
        out.append(f'{winner(g)}最多落后 {dr["comeback"]} 分')
    sec = dr.get("close_seconds_q4") or 0
    if sec >= 120:
        span = "第四节和加时" if g.get("overtimes") else "第四节"
        dur = f'{sec // 60} 分钟' if sec % 60 == 0 else f'{sec // 60} 分 {sec % 60} 秒'
        out.append(f'{span}里分差没超过 5 分的净时间共 {dur}')
    if g.get("series"):
        out.append(g["series"])
    return out


OUTLINES = {
    "clutch": [
        ("那一球", 150,
         "只写这一球：谁在什么位置、用什么方式、防守人是谁。写完就停，不要顺手评价「大心脏」。"),
        ("倒回去", 300,
         "比分是怎么走到这一步的 —— 反超之前最后两分钟，双方各自靠什么得分。"
         "有加时就从加时的第一个回合写起，别从第四节开头抄一遍。"),
        ("输的那边", 250,
         "最后 30 秒他们的选择：犯规还是让时间走完、暂停之后第一选择是谁、结果是什么。"
         "只写做了什么，不写「虽败犹荣」。"),
        ("收尾", 100,
         "一句事实收住，再抛一个问题把评论引进来 —— 比如「如果那个球没进，现在是谁在庆祝」。"),
    ],
    "comeback": [
        ("结果先给", 120,
         f"开场就把最大落后分差和最终比分放出来。别按节次从头讲，读者会走。"),
        ("从最深的坑写起", 350,
         "从落后最多的那一刻开始，写清是一波几比几、谁连得几分、对方那段时间投丢了多少。"),
        ("反超那一刻", 250,
         "反超球是谁投的、发生在第几节剩多少秒 —— 这是全文第二个高点，要比第一节写细。"),
        ("收尾", 120,
         "把「落后多少分赢球」这个数字再点一次，然后收住。别升华。"),
    ],
    "close": [
        ("最后一攻", 150,
         "直接从第四节最后两分钟切入，不要交代前三节。"),
        ("前面三节", 120,
         "压成一句话：谁先领先、最多领先多少、什么时候被追平。"),
        ("逐回合", 350,
         "把最后三分钟一回合一回合过一遍，每个回合只写结果和用时，不写战术名词。"),
        ("收尾", 100,
         "用交替领先次数和最终分差收尾，一句话。"),
    ],
    "blowout": [
        ("先别急着发", 0,
         "这种比分头条不给推荐。除非有别的钩子（球星破纪录、主力伤退、某节打出 20-0），"
         "否则头条今天别发长文，改发一条微头条。"),
        ("公众号还能写", 0,
         "次条读者是已经关注你的人，可以只写这场里的一个细节：某一节的攻防、某个替补的爆发、"
         "或者赢的那队做对了哪件小事。不要写「全面碾压」。"),
    ],
}


ADVICE_TMPL = """\
| 项目 | 公众号次条 | 头条号 |
| --- | --- | --- |
| 字数 | 1200–1600 字 | 800–1200 字 |
| 开头 | 先接一句主条：「今天 {total} 场，这条只讲一场」 | 不提「今天几场」，第一句就是那一球 |
| 人称 | 可以用「我们」 | 用「你」，读者是陌生人 |
| 数据密度 | 可以密，读者是来看细节的 | 一段最多两个数字，多了划走 |
| 结尾 | 引到主条：「完整战报在今天头条」 | 抛问题引评论，别导流 |
| 配图 | 封面 + 走势图都能用 | 只能 1 张（头条不认外链图，得手动上传） |
"""


# ------------------------------------------------------------------ 渲染

def render(g, d, total):
    date_cn = d.get("game_date") or ""
    y, mo, dd = (str(date_cn).split("-") + ["", "", ""])[:3]
    pretty = f"{int(y)}年{int(mo)}月{int(dd)}日" if y and mo and dd else date_cn
    postseason = "季后赛" if d.get("postseason") else "常规赛"

    out = [f"# 今日主打 · {pretty}（美国时间）", ""]
    out.append(f"> {BRAND} ｜ 公众号次条 + 头条号，两个平台都只发这一场。")
    out.append("")

    if not g:
        out.append(f"今天没有{postseason}。次条不用出，头条也别发长文 —— 没比赛的日子发战报，"
                   f"两个平台的完读率都很难看。")
        out.append("")
        t = d.get("tomorrow") or {}
        p = t.get("pick") or {}
        if t.get("status") == "play" and p:
            bj = " ".join(x for x in (p.get("bj_date") or "", p.get("bj_time") or "") if x)
            out.append(f"如果一定要发，就发明天的预告：{p.get('away')} @ {p.get('home')}"
                       + (f"，北京时间 {bj}" if bj else "")
                       + f"。那天全联盟 {t.get('total') or 0} 场。")
        elif t.get("status") == "idle":
            out.append(f"下一场比赛在美国时间 {t.get('date_cn') or '待定'}，"
                       f"到时候再恢复更新就行，不用特意发停更声明。")
        out.append("")
        return "\n".join(out)

    kind = kind_of(g)
    head = (f"今天{postseason} {total} 场，只挑这一场" if total > 1
            else f"今天只有 1 场{postseason}")
    out.append(f"{head}：**{vs(g)}**"
               + (f"（{g['overtimes']} 个加时）" if g.get("overtimes") else "")
               + f" · {KIND_CN[kind]}")
    out.append("")
    if g.get("label"):
        out.append(f"这场在主条里被标了「{g['label']}」，次条顺着往下深挖就行。")
        out.append("")

    # 1. 标题
    out.append("## 1. 标题")
    out.append("")
    tt = titles_toutiao(g)
    out.append(f"**头条号**（限 {TITLE_LIMIT} 字，超了会被截断）")
    out.append("")
    for i, t in enumerate(tt, 1):
        out.append(f"{i}. {t}（{len(t)} 字）")
    out.append("")
    wx = titles_wechat(g)
    out.append("**公众号次条**（信息流只露前 20 字，钩子必须在最前面）")
    out.append("")
    for i, t in enumerate(wx, 1):
        out.append(f"{i}. {t}")
    out.append("")
    dg = digest(g)
    if dg:
        out.append(f"**摘要**（群发时显示在标题下面，已压到 54 字内）：{dg}")
        out.append("")

    # 2. 开场
    out.append("## 2. 开场（可以直接用，改改语气就行）")
    out.append("")
    out.append(f"> {opener(g)}")
    out.append("")

    # 3. 骨架
    out.append("## 3. 正文骨架")
    out.append("")
    for i, (name, words, tip) in enumerate(OUTLINES[kind], 1):
        w = f"约 {words} 字" if words else ""
        out.append(f"**{i}. {name}**{'（' + w + '）' if w else ''}")
        out.append("")
        out.append(f"{tip}")
        out.append("")

    # 4. 数据
    out.append("## 4. 能用的数字（都能在 ESPN 复核，别改数）")
    out.append("")
    for f in facts_of(g):
        out.append(f"- {f}")
    out.append("")

    fa = [f for f in (d.get("focus") or [])
          if f.get("state") == "played" and f.get("team") in (g["away"], g["home"])]
    if fa:
        out.append("这场里的焦点球星：")
        out.append("")
        for f in fa:
            bits = [f'{f.get("pts") or 0} 分']
            if f.get("reb") and str(f.get("reb")) != "0":
                bits.append(f'{f["reb"]} 板')
            if f.get("ast") and str(f.get("ast")) != "0":
                bits.append(f'{f["ast"]} 助')
            out.append(f'- {f.get("cn") or f.get("team")}：{" ".join(bits)}')
        out.append("")

    # 5. 配图
    out.append("## 5. 配图")
    out.append("")
    out.append("- 封面：`docs/cover.png` 就是这一场的比分牌，两边通用")
    out.append("- 公众号次条可以再插一张走势图 `docs/trend-*.png`（如果有）")
    out.append("- 头条只能 1 张图，且必须后台上传 —— 头条编辑器不认外链图片")
    out.append("- 比赛照片和动图都是版权素材，别用")
    out.append("")

    # 6. 差异
    out.append("## 6. 两边别写成一样")
    out.append("")
    out.append(ADVICE_TMPL.format(total=total).replace(
        "「今天 1 场，这条只讲一场」", "「今天只有这一场，就讲它」"))
    out.append("")
    out.append("同一场在两个平台都发是没问题的，被判「搬运」的前提是文字高度雷同。")
    out.append("标题换措辞、开头换人称、段落顺序调一下，基本就安全了。")
    out.append("")

    return "\n".join(out).rstrip() + "\n"


def main():
    if not LATEST.exists():
        print("没有 latest.json，跳过今日主打")
        return 0
    d = load_json(LATEST, {})
    if not d:
        print("latest.json 读不出来，跳过今日主打")
        return 0

    games = d.get("games") or []
    g = pick_feature(games, d.get("focus"), d.get("headline"))

    TARGET.write_text(render(g, d, len(games)), encoding="utf-8")

    brief = {
        "date": d.get("game_date"),
        "pick": vs(g) if g else None,
        "kind": KIND_CN[kind_of(g)] if g else None,
        "title": (titles_toutiao(g) or [""])[0] if g else None,
    }
    BRIEF.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")

    if g:
        print(f"今日主打：{vs(g)}（{KIND_CN[kind_of(g)]}）→ {TARGET.name}")
    else:
        print(f"今天没有比赛，今日主打只留了提示 → {TARGET.name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"今日主打生成失败：{exc}", file=sys.stderr)
        sys.exit(1)
