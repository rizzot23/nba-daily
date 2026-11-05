#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NBA 每日战报生成器

数据源（按优先级）：
  1. ESPN site.api   —— 无需 Key，比分 / 单节 / 球队统计 / 球员数据全都有
  2. balldontlie     —— 备用，仅比分（免费档不含 /stats）

流程：拉取比赛日全部比赛 -> 聚合核心数据 -> 生成可直接粘贴进公众号的 HTML

环境变量：
  REPORT_GAME_DATE     可选，覆盖比赛日（YYYY-MM-DD，按美国比赛日算），默认取北京时间昨天
  BALLDONTLIE_API_KEY  可选，仅在 ESPN 不可用时作为比分兜底
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart import AWAY_HEX as CHART_AWAY_HEX, HOME_HEX as CHART_HOME_HEX, score_chart  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    BJ_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # 极老 Python 兜底
    BJ_TZ = timezone(timedelta(hours=8))

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR.parent / "docs"
TEAMS_FILE = BASE_DIR / "teams_zh.json"
PLAYERS_FILE = BASE_DIR / "players_zh.json"
FOCUS_FILE = BASE_DIR / "focus.json"
IDLE_FILE = BASE_DIR / "idle_notes.json"

# 明日休战时，往后最多找多少天，够跨过全明星周末和圣诞这种长假
LOOKAHEAD_DAYS = 14

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
BDL_BASE = "https://api.balldontlie.io/v1"
BDL_KEY = os.environ.get("BALLDONTLIE_API_KEY", "").strip()

# ESPN 不是公开授权接口，频率放低一点，避免被限
REQ_INTERVAL = 1.2
_last_request_at = 0.0


# ---------------------------------------------------------------- 网络层

def _throttle():
    global _last_request_at
    elapsed = time.time() - _last_request_at
    if elapsed < REQ_INTERVAL:
        time.sleep(REQ_INTERVAL - elapsed)
    _last_request_at = time.time()


def http_json(url, headers=None, retries=3):
    hdrs = {"User-Agent": "Mozilla/5.0 (compatible; nba-daily-report/2.0)", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    last_err = None
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:200]
            last_err = f"HTTP {e.code}：{body}"
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * attempt)
                continue
            raise RuntimeError(last_err)
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = f"网络错误：{e}"
            if attempt < retries:
                time.sleep(4 * attempt)
    raise RuntimeError(last_err or "请求失败")


# ---------------------------------------------------------------- 静态映射

def load_json(path):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def cn_team(full_name, mapping):
    return mapping.get(full_name) or full_name


def normalize_name(name):
    """去掉重音、花式撇号和句点，让 Jokić / Jokic、D'Angelo / D’Angelo、
    P.J. Washington / PJ Washington 都能命中同一份表。

    句点是删掉而不是换成空格：ESPN 有时写 "P.J."、有时写 "PJ"，
    换空格会变成 "p j" 和 "pj" 两种 key，删点才能归到一起。
    """
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace(".", "")
    return " ".join(s.lower().split())


def cn_player(display_name, mapping):
    """中文名优先，查不到就用姓氏原文，避免名单过长后维护不动。"""
    if not display_name:
        return "未知"
    hit = mapping.get(normalize_name(display_name))
    if hit:
        return hit
    parts = [p for p in display_name.split() if p not in ("Jr.", "Sr.", "II", "III", "IV")]
    return parts[-1] if parts else display_name


# ---------------------------------------------------------------- 取数层

def resolve_game_date():
    override = os.environ.get("REPORT_GAME_DATE", "").strip()
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    # 北京时间今天的战报，对应美国的「昨天」比赛日
    return datetime.now(BJ_TZ).date() - timedelta(days=1)


def fetch_scoreboard(game_date):
    """ESPN 记分板。dates 为美国东部比赛日。"""
    ymd = game_date.strftime("%Y%m%d")
    payload = http_json(f"{ESPN_SITE}/scoreboard?dates={ymd}")
    return payload.get("events") or []


def fetch_summary(event_id):
    return http_json(f"{ESPN_SITE}/summary?event={event_id}")


def fetch_scores_bdl(game_date):
    """备用：只拿比分，字段结构与 ESPN 解析结果保持独立。"""
    if not BDL_KEY:
        raise RuntimeError("ESPN 不可用，且未设置 BALLDONTLIE_API_KEY")
    d = game_date.strftime("%Y-%m-%d")
    url = f"{BDL_BASE}/games?" + urllib.parse.urlencode([("dates[]", d), ("per_page", "100")])
    payload = http_json(url, headers={"Authorization": BDL_KEY})
    out = []
    for g in payload.get("data") or []:
        out.append({
            "home": {"name_en": g["home_team"]["full_name"], "score": g.get("home_team_score"),
                     "lines": [], "stats": {}, "record": ""},
            "away": {"name_en": g["visitor_team"]["full_name"], "score": g.get("visitor_team_score"),
                     "lines": [], "stats": {}, "record": ""},
            "finished": str(g.get("status", "")).lower() == "final",
            "tipoff_bj": "",
            "scorers": {"home": [], "away": []},
        })
    return out


# ---------------------------------------------------------------- 解析层

STAT_KEYS = ("PTS", "REB", "AST")


def _linescores(competitor):
    vals = []
    for ls in competitor.get("linescores") or []:
        try:
            vals.append(int(float(ls.get("displayValue"))))
        except (TypeError, ValueError):
            vals.append(None)
    return vals


def _team_stats(team_block):
    out = {}
    for s in team_block.get("statistics") or []:
        out[s.get("name")] = s.get("displayValue")
    return out


def _scorers(players_block, limit=3):
    """每队取得分最高的 N 人。"""
    out = []
    for group in players_block.get("statistics") or []:
        labels = [str(x).upper() for x in (group.get("labels") or [])]
        try:
            i_pts = labels.index("PTS")
        except ValueError:
            continue
        i_reb = labels.index("REB") if "REB" in labels else None
        i_ast = labels.index("AST") if "AST" in labels else None

        rows = []
        for ath in group.get("athletes") or []:
            stats = ath.get("stats") or []
            if not stats or len(stats) <= i_pts:
                continue
            try:
                pts = int(str(stats[i_pts]).split("-")[0])
            except (TypeError, ValueError):
                continue
            rows.append({
                "name": (ath.get("athlete") or {}).get("displayName", ""),
                "pts": pts,
                "reb": stats[i_reb] if i_reb is not None and i_reb < len(stats) else "",
                "ast": stats[i_ast] if i_ast is not None and i_ast < len(stats) else "",
            })
        rows.sort(key=lambda r: r["pts"], reverse=True)
        out = rows[:limit]
        break  # 一组就够
    return out


def _all_players(players_block, side):
    """整队球员逐个取出，供焦点球星匹配用（_scorers 只留前 3，不够查）。"""
    out = []
    for group in players_block.get("statistics") or []:
        labels = [str(x).upper() for x in (group.get("labels") or [])]
        if "PTS" not in labels:
            continue
        idx = {k: labels.index(k) for k in STAT_KEYS if k in labels}
        for ath in group.get("athletes") or []:
            stats = ath.get("stats") or []
            if not stats or len(stats) <= idx["PTS"]:
                continue
            name = (ath.get("athlete") or {}).get("displayName") or ""
            if not name:
                continue
            out.append({
                "id": str((ath.get("athlete") or {}).get("id") or ""),
                "name": name,
                "side": side,
                "pts": str(stats[idx["PTS"]]).split("-")[0],
                "reb": stats[idx["REB"]] if idx.get("REB", 99) < len(stats) else "",
                "ast": stats[idx["AST"]] if idx.get("AST", 99) < len(stats) else "",
            })
        break  # 一组就够
    return out


def _clock_seconds(clock):
    """'3:59' -> 239.0，'1.8' -> 1.8。解析不了返回 None。"""
    s = ((clock or {}).get("displayValue") or "").strip()
    if ":" in s:
        try:
            m, sec = s.split(":")
            return int(m) * 60 + float(sec)
        except (ValueError, TypeError):
            return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _elapsed_seconds(period, clock):
    """把「第几节 + 剩余秒数」换成开场至今的累计秒数，供走势图当横轴。"""
    if not period:
        return 0.0
    clock = clock or 0.0
    if period <= 4:
        return (period - 1) * 720 + (720 - clock)
    return 4 * 720 + (period - 5) * 300 + (300 - clock)


def _scorer_side(plays, i):
    """这条回合是谁得的分。拿相邻回合的比分差反推，比依赖 team.id 稳。"""
    p = plays[i]
    h, a = p.get("homeScore"), p.get("awayScore")
    if h is None or a is None:
        return None
    for j in range(i - 1, max(-1, i - 6), -1):
        ph, pa = plays[j].get("homeScore"), plays[j].get("awayScore")
        if ph is None or pa is None:
            continue
        if h > ph:
            return "home"
        if a > pa:
            return "away"
        return None
    return None


def detect_clutch(plays, final_home, final_away, athletes=None):
    """识别绝杀 / 准绝杀。

    判据全部来自逐回合数据，可以复核：
      1. 取「败方最后一次得分」之后的比赛段 —— 那之后才是真正定胜负的时间
      2. 这一段里胜方第一次得分，必须把比分从打平或落后变成领先（反超球）
      3. 那球发生在第四节或加时，剩余 ≤ 24 秒

    这样处理是因为反超之后对手常常只能犯规，胜方还能靠罚球涨分；
    若简单取「全场最后一次进球」，这类真正的好球会被漏掉。
    剩余 ≤ 1 秒算「绝杀」，1～24 秒算「准绝杀」。
    """
    if not plays or final_home is None or final_away is None or final_home == final_away:
        return None
    athletes = athletes or {}
    winner_side = "home" if final_home > final_away else "away"
    loser_side = "away" if winner_side == "home" else "home"

    last_loser = -1
    for i in range(len(plays)):
        if plays[i].get("scoringPlay") and _scorer_side(plays, i) == loser_side:
            last_loser = i

    for i in range(last_loser + 1, len(plays)):
        p = plays[i]
        if not p.get("scoringPlay") or _scorer_side(plays, i) != winner_side:
            continue
        period = (p.get("period") or {}).get("number") or 0
        if period < 4:
            continue
        clock = _clock_seconds(p.get("clock"))
        if clock is None or clock > 24:
            continue
        h, a = p.get("homeScore"), p.get("awayScore")
        val = p.get("scoreValue") or 0
        if not val or h is None or a is None:
            continue
        after = h - a if winner_side == "home" else a - h     # 这球打完后领先多少
        before = after - val                                   # 这球之前领先多少
        if after <= 0 or before > 0:
            continue                                           # 不是反超球，继续往后找

        pid = ""
        parts = p.get("participants") or []
        if parts:
            pid = str(((parts[0] or {}).get("athlete") or {}).get("id") or "")

        return {
            "kind": "buzzer" if clock <= 1.0 else "winner",
            "period": period,
            "clock": clock,
            "points": val,
            "margin": after,
            "before": before,
            "player_en": athletes.get(pid, ""),
            "side": winner_side,
            "overtime": period > 4,
        }
    return None


FOOT_RE = re.compile(r"(\d+)-foot")


def extract_actions(plays, athletes, game):
    """从逐回合里挑出可能上集锦的动作。

    只认四种能靠文本判断的：空接、扣篮、28 英尺外三分、第四节的盖帽。
    这不是 NBA 官方十佳球（那个没有逐场接口），是本报告自己看数据挑的高光候选。
    """
    out = []
    for p in plays:
        txt = (p.get("text") or "").lower()
        typ = ((p.get("type") or {}).get("text") or "").lower()
        if "alley-oop" in txt or "alley oop" in txt:
            kind = "alley"
        elif "dunk" in txt:
            kind = "dunk"
        elif "block" in typ:
            kind = "block"
        elif "three point" in txt:
            kind = "three"
        else:
            continue

        if kind != "block" and not p.get("scoringPlay"):
            continue

        m = FOOT_RE.search(txt)
        dist = int(m.group(1)) if m else None
        if kind == "three" and (dist or 0) < 28:
            continue                      # 普通三分不算高光

        period = (p.get("period") or {}).get("number") or 0
        if kind == "block" and period < 4:
            continue                      # 前三节的盖帽太常见

        tid = str((p.get("team") or {}).get("id") or "")
        side = None
        for s in ("home", "away"):
            if tid and tid == game[s].get("team_id"):
                side = s
                break
        if not side:
            continue

        pid = ""
        for pa in p.get("participants") or []:
            pid = str(((pa or {}).get("athlete") or {}).get("id") or "")
            if pid:
                break

        clock = _clock_seconds(p.get("clock"))
        score = {"alley": 60, "dunk": 22, "block": 16, "three": 30}.get(kind, 0)
        if kind == "three":
            score += max(0, ((dist or 25) - 25) * 2)
        if period >= 4:
            score += 30
        if period > 4:
            score += 15
        if clock is not None and clock <= 1.0:
            score += 80 if period >= 4 else 30   # 末节压哨最贵，节间压哨只是花絮

        out.append({
            "kind": kind,
            "dist": dist,
            "period": period,
            "clock": clock,
            "side": side,
            "player_en": athletes.get(pid, ""),
            "score": score,
        })
    return out


def pick_best_action(games):
    """全天所有比赛里最炸的那个动作。绝杀压过一切。"""
    best, best_score = None, None
    for g in games:
        if not g.get("finished"):
            continue
        cl = (g.get("drama") or {}).get("clutch")
        if cl:
            cand = {
                "kind": "clutch",
                "player_en": cl.get("player_en", ""),
                "period": cl["period"],
                "clock": cl["clock"],
                "side": cl["side"],
                "dist": None,
                "score": 999,
            }
            if best_score is None or cand["score"] > best_score:
                best, best_score = (g, cand), cand["score"]
            continue
        for a in g.get("actions") or []:
            if best_score is None or a["score"] > best_score:
                best, best_score = (g, a), a["score"]
    # 分数太低说明当天没什么名场面，宁可不写，也别拿个第三节普通扣篮充数
    return best if best and best[1]["score"] >= 45 else None


def analyze_drama(plays, final_home, final_away, athletes=None):
    """从逐回合数据算激烈度。打平与交替领先都按「状态跃迁」计数，不按球数。"""
    stats = {
        "lead_changes": 0,
        "ties": 0,
        "comeback": 0,
        "final2_max_diff": None,
        "close_period": None,
        "close_clock": None,
        "close_seconds": 0,
        "max_lead": 0,
        "series": [],
        "score": 0.0,
        "clutch": None,
        "ok": False,
    }
    if not plays or final_home is None or final_away is None:
        return stats

    prev_diff = None
    prev_sign = 0
    low, high = 0, 0          # 主队视角的分差极值
    last_close = None
    final2 = []
    close_secs = 0.0
    series = []
    seg = None                # (节, 剩余秒数, 分差) 上一个回合

    for p in plays:
        h, a = p.get("homeScore"), p.get("awayScore")
        if h is None or a is None:
            continue
        d = h - a
        sign = (d > 0) - (d < 0)

        if d == 0 and prev_diff not in (None, 0):
            stats["ties"] += 1
        if sign:
            if prev_sign and sign != prev_sign:
                stats["lead_changes"] += 1
            prev_sign = sign
        prev_diff = d
        low, high = min(low, d), max(high, d)

        period = (p.get("period") or {}).get("number") or 0
        clock = _clock_seconds(p.get("clock"))
        if clock is not None:
            series.append((round(_elapsed_seconds(period, clock), 1), h, a))

        # 第四节及加时内「分差≤5」的净时长：按相邻回合的时间差累加，
        # 比只看某个时刻可靠 —— 垃圾时间追分不会把强度算高
        if seg and clock is not None and seg[1] is not None and period >= 4 and seg[0] == period:
            span = seg[1] - clock
            if 0 < span <= 120 and abs(seg[2]) <= 5:
                close_secs += span
        seg = (period, clock, d)

        if period >= 4 and clock is not None:
            if abs(d) <= 5:
                last_close = (period, clock)
            if period > 4 or clock <= 120:
                final2.append(abs(d))

    # 胜方曾经落后多少
    winner_home = final_home > final_away
    stats["comeback"] = max(0, -low) if winner_home else max(0, high)
    stats["max_lead"] = max(0, high) if winner_home else max(0, -low)
    stats["final2_max_diff"] = max(final2) if final2 else None
    stats["close_seconds"] = int(round(close_secs))

    # 走势图最多留 300 个点，够画 1200 像素宽的图了
    if len(series) > 300:
        step = len(series) / 300.0
        series = [series[int(i * step)] for i in range(300)] + [series[-1]]
    stats["series"] = series
    if last_close:
        stats["close_period"], stats["close_clock"] = last_close

    margin = abs(final_home - final_away)
    f2 = stats["final2_max_diff"] if stats["final2_max_diff"] is not None else 12

    stats["score"] = round(
        (20 if margin <= 5 else 0)
        + max(0, 15 - margin)
        + stats["lead_changes"] * 4
        + stats["ties"] * 3
        + max(0, 12 - f2) * 3
        + min(close_secs, 720) / 720.0 * 40
        + min(stats["comeback"], 20),
        1,
    )
    stats["clutch"] = detect_clutch(plays, final_home, final_away, athletes)
    stats["ok"] = True
    return stats


def parse_event(event, mapping):
    comp = (event.get("competitions") or [{}])[0]
    status = (comp.get("status") or {}).get("type") or {}
    finished = bool(status.get("completed"))

    sides = {"home": None, "away": None}
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        if side not in sides:
            continue
        team = c.get("team") or {}
        rec = ""
        # 记分板用 records，详情接口用 record，两处都要兼容
        for r in (c.get("records") or c.get("record") or []):
            if r.get("type") in ("total", None) and r.get("summary"):
                rec = r["summary"]
                break
        sides[side] = {
            "name_en": team.get("displayName") or team.get("name") or "",
            "abbr": team.get("abbreviation") or "",
            "team_id": str(team.get("id") or ""),
            # ESPN 给的是不带 # 的六位十六进制，画封面渐变时用
            "color": (team.get("color") or "").strip(),
            "score": int(c["score"]) if str(c.get("score", "")).isdigit() else None,
            "lines": _linescores(c),
            "record": rec,
            "stats": {},
        }

    if not sides["home"] or not sides["away"]:
        return None

    # 赛季类型：2=常规赛，3=季后赛（含附加赛）。猜不出来时按常规赛处理。
    season = event.get("season") or {}
    postseason = int(season.get("type") or 0) == 3 or "post" in str(season.get("slug") or "").lower()

    game = {
        "id": event.get("id"),
        "home": sides["home"],
        "away": sides["away"],
        "finished": finished,
        "postseason": postseason,
        "series": None,
        "status_text": status.get("description") or "",
        "tipoff_bj": "",
        "scorers": {"home": [], "away": []},
        "roster": [],
        "venue": "",
        "drama": {},
        "actions": [],
    }

    # 开球时间换算成北京时间
    iso = event.get("date")
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BJ_TZ)
            game["tipoff_bj"] = dt.strftime("%H:%M")
        except ValueError:
            pass

    return game


def parse_series(comp, game):
    """系列赛大比分。只认 type=playoff 的那组。

    常规赛也会返回一组 series，但那是「赛季系列赛」（同两队 4 次交手的战绩，
    summary 写作 "NO leads series 1-0"），直接拿来显示会把读者绕晕，所以按 type 过滤。
    另外不要去翻译 summary 那句英文 —— 里面是 ESPN 的队名缩写，和我们的中文队名对不上；
    用 competitors[].wins 配 team id 自己拼才准。
    """
    for s in comp.get("series") or []:
        if (s.get("type") or "").lower() != "playoff":
            continue
        wins = {}
        for c in s.get("competitors") or []:
            tid = str(c.get("id") or "")
            if tid in (game["home"]["team_id"], game["away"]["team_id"]):
                wins[tid] = int(c.get("wins") or 0)
        if len(wins) != 2:
            continue
        hw = wins.get(game["home"]["team_id"], 0)
        aw = wins.get(game["away"]["team_id"], 0)
        return {
            "home": hw,
            "away": aw,
            "total": int(s.get("totalCompetitions") or 0),
            "completed": bool(s.get("completed")),
        }
    return None


def series_text(g):
    """把系列赛比分说成一句人话。不是季后赛或拿不到数据时返回 None。"""
    s = g.get("series")
    if not s:
        return None
    hw, aw = s["home"], s["away"]
    if hw == 0 and aw == 0:
        return None
    home_cn = cn_team(g["home"]["name_en"], TEAM_MAP)
    away_cn = cn_team(g["away"]["name_en"], TEAM_MAP)
    hi, lo = (hw, aw) if hw > aw else (aw, hw)
    lead_cn = home_cn if hw > aw else away_cn

    if hw == aw:
        body = f"系列赛 {hw}-{aw} 打平"
    elif s.get("completed"):
        body = f"{lead_cn} {hi}-{lo} 晋级"
    else:
        body = f"{lead_cn} {hi}-{lo} 领先"
        # 七场四胜制，先到 4 分晋级，3 分就是赛点
        if hi == 3:
            body += " · 手握赛点"
    return body


def enrich_with_summary(game, summary, mapping):
    """补球队统计、单节比分、球员数据。任一项失败不影响主流程。"""
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]

    # 季后赛才有意义：系列赛大比分。常规赛返回的那组是"赛季系列赛"，parse_series 里已过滤
    try:
        game["series"] = parse_series(comp, game)
    except Exception:
        game["series"] = None
    if game["series"]:
        game["postseason"] = True

    # 用 header 里的数据校正比分与单节（比 scoreboard 更完整）
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        if side not in ("home", "away"):
            continue
        try:
            game[side]["score"] = int(c["score"])
        except (KeyError, TypeError, ValueError):
            pass
        lines = _linescores(c)
        if lines:
            game[side]["lines"] = lines

    box = summary.get("boxscore") or {}

    for t in box.get("teams") or []:
        full = ((t.get("team") or {}).get("displayName")) or ""
        for side in ("home", "away"):
            if full and full == game[side]["name_en"]:
                game[side]["stats"] = _team_stats(t)

    for p in box.get("players") or []:
        full = ((p.get("team") or {}).get("displayName")) or ""
        for side in ("home", "away"):
            if full and full == game[side]["name_en"]:
                game["scorers"][side] = _scorers(p)
                game["roster"].extend(_all_players(p, side))

    venue = ((summary.get("gameInfo") or {}).get("venue") or {}).get("fullName")
    if venue:
        game["venue"] = venue

    plays = summary.get("plays") or []
    athletes = {p["id"]: p["name"] for p in game["roster"] if p.get("id")}
    game["drama"] = analyze_drama(
        plays, game["home"]["score"], game["away"]["score"], athletes
    )
    game["actions"] = extract_actions(plays, athletes, game)

    return game


# ---------------------------------------------------------------- 洞察层

def fmt_clock(sec):
    """239 -> '3:59'，44 -> '0:44'。"""
    if sec is None:
        return ""
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def build_hook(g, is_headline=False):
    """从数据里直接算出一句话看点，供人工改写时当抓手。

    头条场次的看点由导语承担，这里换一个角度，避免两处说同一件事。
    """
    hs, as_ = g["home"]["score"], g["away"]["score"]
    if hs is None or as_ is None:
        return ""
    if hs == as_:
        return f"双方 {hs} 平，进入加时。"

    win, lose = (g["home"], g["away"]) if hs > as_ else (g["away"], g["home"])
    margin = abs(hs - as_)
    win_cn = cn_team(win["name_en"], TEAM_MAP)
    lose_cn = cn_team(lose["name_en"], TEAM_MAP)
    dr = g.get("drama") or {}

    lead = (win["stats"].get("largestLead") or "").strip()
    try:
        lead_i = int(lead)
    except ValueError:
        lead_i = 0

    lc = dr.get("lead_changes") or 0
    ties = dr.get("ties") or 0
    close_secs = dr.get("close_seconds") or 0

    # 来回拉扯型：只在真正缠斗过（第四节有胶着时长）时才这么写
    if not is_headline and lc >= 4 and close_secs >= 60 and margin <= 12:
        return f"全场交替领先 {lc} 次、打平 {ties} 次，{win_cn}最后阶段才拉开 {margin} 分。"

    # 末节追分型
    wl, ll = win["lines"], lose["lines"]
    if len(wl) >= 4 and len(ll) >= 4 and wl[-1] is not None and ll[-1] is not None:
        gap = ll[-1] - wl[-1]
        if gap >= 10 and margin <= gap + 4:
            return f"{lose_cn}末节打出 {ll[-1]}-{wl[-1]}，但前面落后太多，最终仍差 {margin} 分。"

    # 逆转型
    cb = dr.get("comeback") or 0
    if cb >= 10:
        return f"{win_cn}一度落后 {cb} 分，翻盘赢 {margin} 分。"

    if margin <= 5:
        return f"{win_cn}只赢 {margin} 分，最后时刻才定胜负。"

    if lead_i >= margin + 12:
        return f"{win_cn}最多领先 {lead_i} 分，末段被追到 {margin} 分。"

    if lead_i:
        return f"{win_cn}最多领先 {lead_i} 分，最终赢 {margin} 分。"

    return f"{win_cn}赢 {margin} 分。"


def pick_headline(played):
    """选当日最胶着的一场。绝杀场优先 —— 那是当天最不可替代的瞬间。"""
    if not played:
        return None
    scored = [g for g in played if (g.get("drama") or {}).get("ok")]
    if not scored:
        return min(played, key=lambda g: abs((g["home"]["score"] or 0) - (g["away"]["score"] or 0)))

    def rank(g):
        dr = g["drama"]
        return dr["score"] + (60 if dr.get("clutch") else 0)

    return max(scored, key=rank)


LABELS = {
    "drama": ("今日最胶着", "#c2410c"),
    "comeback": ("今日最大逆转", "#1d6fa5"),
    "fallen": ("今日最功亏一篑", "#7a4b8f"),
    "flat": ("今日最平淡", "#9a9a9a"),
}

# 一场详写的上限。常规赛收官日会 30 队同天开打，全展开页面会长得没法看
MAX_DETAIL = 15


def assign_labels(played):
    """给每场最多贴一个标签，按优先级从高到低分配，避免一场挂好几个。

    判定都用可复核的数据，不靠主观：
      最胶着   —— 激烈度得分最高
      最大逆转 —— 胜方落后分差最大，且至少 10 分
      最功亏一篑 —— 一度落后 10 分以上、末节追到 5 分内却仍输球
      最平淡   —— 激烈度最低，且分差上两位数、末节几乎没缠斗过
    """
    out = {}
    pool = [g for g in played if (g.get("drama") or {}).get("ok")]
    if len(pool) < 2:
        return out

    def margin(g):
        return abs(g["home"]["score"] - g["away"]["score"])

    # 1. 最胶着
    head = max(pool, key=lambda g: g["drama"]["score"])
    out[head["id"]] = "drama"
    rest = [g for g in pool if g["id"] != head["id"]]

    # 2. 最大逆转
    cands = [g for g in rest if (g["drama"].get("comeback") or 0) >= 10]
    if cands:
        best = max(cands, key=lambda g: g["drama"]["comeback"])
        out[best["id"]] = "comeback"
        rest = [g for g in rest if g["id"] != best["id"]]

    # 3. 最功亏一篑
    cands = []
    for g in rest:
        dr = g["drama"]
        got_close = (dr.get("close_period") == 4 and (dr.get("close_clock") or 9999) <= 360)
        if (dr.get("max_lead") or 0) >= 10 and margin(g) <= 8 and got_close:
            cands.append(g)
    if cands:
        best = max(cands, key=lambda g: (g["drama"]["max_lead"], -margin(g)))
        out[best["id"]] = "fallen"
        rest = [g for g in rest if g["id"] != best["id"]]

    # 4. 最平淡
    cands = [
        g for g in rest
        if margin(g) >= 10
        and (g["drama"].get("close_seconds") or 0) <= 60
        and (g["drama"].get("lead_changes") or 0) <= 6
    ]
    if cands:
        out[min(cands, key=lambda g: g["drama"]["score"])["id"]] = "flat"

    return out


def build_lead(games):
    """导语：不再报总分，直接点出当天最值得看的那一场。"""
    played = [g for g in games if g.get("finished") and g["home"]["score"] is not None]
    if not played:
        return "今天没有比赛。"

    head = pick_headline(played)
    if head is None:
        return f"今天 {len(played)} 场。"

    hs, as_ = head["home"]["score"], head["away"]["score"]
    away_cn = cn_team(head["away"]["name_en"], TEAM_MAP)
    home_cn = cn_team(head["home"]["name_en"], TEAM_MAP)
    win = head["home"] if hs > as_ else head["away"]
    win_cn = cn_team(win["name_en"], TEAM_MAP)
    margin = abs(hs - as_)
    dr = head.get("drama") or {}

    facts = []
    lc = dr.get("lead_changes") or 0
    ties = dr.get("ties") or 0

    # 头条是绝杀场时，整句直接围绕那一球写，比数列举更有画面
    # 措辞用「一刻」不用「一场」：绝杀场未必是全天最胶着的那场，
    # 说「最狠的一场」会和下面挂的「今日最胶着」徽章互相打脸
    clutch = clutch_text(head)
    if clutch:
        # 绝杀场不能只写那一球。11-04 热火落后 20 分、加时压哨翻盘，
        # 原句却补了句「交替领先 8 次」——这是全天最好的一场，
        # 却把最弱的那个数据当成了背景，等于把素材扔了。
        cb = dr.get("comeback") or 0
        ot = overtimes(head)
        tail_bits = []
        if cb >= 12:
            tail_bits.append(f"一度落后 {cb} 分")
        if ot:
            tail_bits.append("多打一个加时" if ot == 1 else f"多打 {ot} 个加时")
        if tail_bits:
            extra = "，他们" + "、".join(tail_bits)
        else:
            extra = f"，全场交替领先 {lc} 次" if lc else ""
        return (
            f"今天 {len(played)} 场，最狠的一刻出在{away_cn} {as_}-{hs} {home_cn}："
            f"{clutch['detail']}{extra}。"
        )

    if lc:
        facts.append(f"交替领先 {lc} 次")
    if ties:
        facts.append(f"打平 {ties} 次")

    period, clock = dr.get("close_period"), dr.get("close_clock")
    if period and clock is not None:
        if period == 4 and clock <= 5:
            facts.append("直到终场分差都没超过 5 分")
        elif period == 4 and clock <= 120:
            facts.append(f"最后 {fmt_clock(clock)} 分差还在 5 分以内")
        elif period == 4:
            facts.append(f"第 4 节还剩 {fmt_clock(clock)} 才把分差拉开到 5 分以上")
        else:
            facts.append("打到加时才分出胜负")

    cb = dr.get("comeback") or 0
    if cb >= 10:
        facts.append(f"{win_cn}一度落后 {cb} 分")

    tail = "，".join(facts) if facts else f"最终 {margin} 分差"
    return (
        f"今天 {len(played)} 场，最胶着的是{away_cn} {as_}-{hs} {home_cn}：{tail}。"
    )


def build_focus(games):
    """当日焦点球星（`focus.json` 里的固定追踪名单）。

    这是追踪名单，不是当日评选榜。名单上的人每天都要出现，
    跟当天打得好不好无关 —— 0 分 0 板 0 助也照列，缺阵和球队休战
    也各自写明。别加「数据太低就不显示」「只留得分最高的几个」
    这类按表现过滤的逻辑，那会把这个区改成另一个当日最佳榜。

    三种状态都要交代，否则只列一个上场的人反而更让人疑惑：
      played —— 有数据（含全 0）
      dnp    —— 球队当天打了，但他没上（缺阵/轮休）
      idle   —— 球队当天没比赛
    """
    try:
        conf = load_json(FOCUS_FILE)
    except Exception:
        return []
    if not isinstance(conf, list) or not conf:
        return []

    played = [g for g in games if g.get("finished")]

    # 当天有比赛的球队 -> (比赛, 主客)
    team_game = {}
    for g in played:
        for side in ("home", "away"):
            team_game.setdefault(g[side]["name_en"], (g, side))

    # 当天真正上过场的人（扫全部名单，避免被配置里的旧队名误导）
    on_court = {}
    for g in played:
        for p in g.get("roster") or []:
            on_court.setdefault(normalize_name(p["name"]), (g, p))

    def matchup(g, side):
        other = "away" if side == "home" else "home"
        mine, theirs = g[side]["score"], g[other]["score"]
        return {
            "team": cn_team(g[side]["name_en"], TEAM_MAP),
            "opp": cn_team(g[other]["name_en"], TEAM_MAP),
            "result": "胜" if (mine or 0) > (theirs or 0) else "负",
        }

    out = []
    for f in conf:
        cn = f.get("cn") or f.get("en", "")
        hit = on_court.get(normalize_name(f.get("en", "")))
        if hit:
            g, p = hit
            row = {"cn": cn, "state": "played", **matchup(g, p["side"]),
                   "pts": p["pts"], "reb": p["reb"], "ast": p["ast"]}
        elif f.get("team") in team_game:
            g, side = team_game[f["team"]]
            row = {"cn": cn, "state": "dnp", **matchup(g, side),
                   "pts": "", "reb": "", "ast": ""}
        else:
            row = {"cn": cn, "state": "idle", "team": f.get("team_cn") or "",
                   "opp": "", "result": "", "pts": "", "reb": "", "ast": ""}
        out.append(row)

    # 全联盟都歇着的时候不摆这一块，免得五行“今日无比赛”
    if not any(r["state"] in ("played", "dnp") for r in out):
        return []

    # 打过的排前面：第一行就该是干货，同组内保持 focus.json 的顺序
    rank = {"played": 0, "dnp": 1, "idle": 2}
    out.sort(key=lambda r: rank[r["state"]])
    return out


def render_focus(items):
    """焦点球星区：上场的给数据，没上的说明原因，读者不至于追着问。"""
    if not items:
        return ""

    rows = []
    for it in items:
        if it["state"] == "idle":
            continue        # 当天没比赛就不提，免得占行

        if it["state"] == "dnp":
            # 球队打了但人没上：压灰，只交代球队结果
            rows.append(
                f'<div style="font-size:13px;line-height:2.2;color:#b0b0b0;'
                f'font-family:{FONT};">'
                f'<span>{esc(it["cn"])}</span>'
                f'<span style="font-size:11px;padding-left:4px;">（未出场）</span>'
                f'<span style="font-size:11.5px;padding-left:8px;">'
                f'{esc(it["team"])} {it["result"]} {esc(it["opp"])}</span>'
                f'</div>'
            )
            continue

        parts = []
        if it["reb"] not in ("", None):
            parts.append(f"{it['reb']}板")
        if it["ast"] not in ("", None):
            parts.append(f"{it['ast']}助")
        extra = " ".join(parts)

        rows.append(
            f'<div style="font-size:13px;line-height:2.3;color:{COLOR_TEXT};font-family:{FONT};">'
            f'<span style="font-weight:700;">{esc(it["cn"])}</span>'
            f'<span style="font-size:15px;font-weight:700;color:{COLOR_ACCENT};'
            f'padding-left:7px;">{esc(it["pts"])}</span>'
            f'<span style="font-size:11px;color:{COLOR_ACCENT};">分</span>'
            f'<span style="font-size:11px;color:#a3a3a3;padding-left:4px;">{esc(extra)}</span>'
            f'<span style="font-size:11px;color:#e0e0e0;padding:0 7px;">·</span>'
            f'<span style="font-size:12px;color:#9a9a9a;">'
            f'{esc(it["team"])} {it["result"]} {esc(it["opp"])}</span>'
            f'</div>'
        )

    if not rows:
        return ""

    return (
        f'<div style="margin:0 0 24px;">'
        + render_section("焦点球星", f"{len(rows)} 人", top=4)
        + f'{"".join(rows)}'
        f'</div>'
    )


# ---------------------------------------------------------------- 推荐比赛

# 值得看的就都写出来，不人为砍到三场——好球多的日子砍掉一场都是浪费。
# 10 只是个安全阀：收官日 30 队同天开打，万一全都够格，推荐块会比正文还长。
WATCH_MAX = 10


def overtimes(g):
    """加时次数：分节得分比 4 节长几节，就是打了几个加时。"""
    return max(0, max(len(g["home"].get("lines") or []),
                      len(g["away"].get("lines") or [])) - 4)


def watch_ok(g, margin):
    """硬门槛：至少占一条才叫好看。一条都占不上就不写。

    「好看」只认能拿数据复核的四类：最后一球定胜负、加时、两位数逆转、
    最后时刻还在一个球以内。主观的"精彩"一律不算——没有标准就会场场都推。

    故意不收「末节贴着打」：4 分球但整节谁也没真追上，读完理由也提不起
    兴趣，列出来只是凑数。宁可只推一场，也不拿平淡场把位置占满。
    分差四五分但领先换了十几回的另算——那是真的你来我往，不是拖着不动。
    """
    dr = g.get("drama") or {}
    if not dr.get("ok"):
        return margin <= 3          # 没有逐回合数据时只能看分差
    if dr.get("clutch"):
        return True
    if overtimes(g):
        return True
    if (dr.get("comeback") or 0) >= 12:
        return True
    if margin <= 3:
        return True
    # 交替领先多，但最后赢十几分，说明后半段早拉开了——理由写"交替领先"
    # 会让人以为看了一场平局，对不上比分。分差放这么宽的才收。
    return (dr.get("lead_changes") or 0) >= 12 and margin <= 8


def watch_rank(g):
    """排序分：激烈度打底，绝杀、加时、大逆转各加码。只影响顺序，不决定收不收。"""
    dr = g.get("drama") or {}
    s = dr.get("score") or 0
    if dr.get("clutch"):
        s += 30
    s += overtimes(g) * 12
    s += min(dr.get("comeback") or 0, 25) * 0.8
    return s


def watch_reason(g, margin):
    """一句话理由。只讲最抓人的那一件，不把四个数据点堆成一句话。

    顺序按「信息量」排，不按数据算出来的先后：绝杀 > 最后时刻反超 >
    加时 > 两位数翻盘 > 最后一球 > 反复易手。准入已经把平淡场挡在外面，
    所以这里不需要"末节没拉开"这类凑数理由。
    """
    dr = g.get("drama") or {}
    cl = dr.get("clutch")
    ot = overtimes(g)
    cb = dr.get("comeback") or 0
    lc = dr.get("lead_changes") or 0
    f2 = dr.get("final2_max_diff")

    if cl and cl.get("kind") == "buzzer":
        return "压哨绝杀"
    if cl:
        return f"最后 {int(round(cl.get('clock') or 0))} 秒反超"
    if ot:
        return "加时才分出胜负" if ot == 1 else f"{ot} 个加时才分出胜负"
    if cb >= 12:
        return f"落后 {cb} 分翻盘"
    if f2 is not None and f2 <= 2:
        return "最后两分钟没超过一个球"
    if lc >= 12:
        return f"交替领先 {lc} 次"
    return f"只差 {margin} 分"


def pick_watchable(played, skip_id=None):
    """挑几场值得看的，按好看程度排。导语讲过的那场跳过，不重复。"""
    picks = []
    for g in played:
        if skip_id and g.get("id") == skip_id:
            continue
        hs, as_ = g["home"]["score"], g["away"]["score"]
        if hs is None or as_ is None:
            continue
        margin = abs(hs - as_)
        if not margin:
            continue
        if not watch_ok(g, margin):
            continue
        picks.append((g, margin))
    picks.sort(key=lambda x: watch_rank(x[0]), reverse=True)
    return [(g, watch_reason(g, m)) for g, m in picks[:WATCH_MAX]]


def render_section(title, note="", top=30):
    """区段标题：左边一道橙条 + 加粗黑字，扫读时能当锚点直接跳。

    只加竖条不加底色——公众号编辑器里整块背景容易和下面的卡片糊成一片，
    而且复制粘贴后底色被压扁的情况很常见。右侧的灰字放口径（几场、按什么排），
    不放形容词。
    """
    note_html = (
        f'<span style="font-size:11px;color:#b0b0b0;font-weight:normal;'
        f'letter-spacing:0;padding-left:9px;">{esc(note)}</span>' if note else ""
    )
    return (
        f'<div style="margin:{top}px 0 10px;font-family:{FONT};">'
        f'<span style="display:inline-block;width:3px;height:15px;background:{COLOR_ACCENT};'
        f'vertical-align:-2px;margin-right:9px;"></span>'
        f'<span style="font-size:15px;font-weight:bold;color:{COLOR_TEXT};'
        f'letter-spacing:1px;">{esc(title)}</span>'
        f'{note_html}'
        f'</div>'
    )


# ---------------------------------------------------------------- 明日焦点

WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def date_cn(d, with_weekday=False):
    s = f"{d.month}月{d.day}日"
    return f"{s}（{WEEKDAY_CN[d.weekday()]}）" if with_weekday else s


def load_idle_notes():
    notes = load_json(IDLE_FILE)
    return notes if isinstance(notes, list) else []


def _note_covers(note, d):
    if note.get("date"):
        return str(note["date"]) == str(d)
    start, end = note.get("start"), note.get("end")
    if start and end:
        return str(start) <= str(d) <= str(end)
    return False


def idle_reason(day_from, day_to, notes):
    """休战区间的原因。只认 idle_notes.json 里登记过的日子，不做猜测。

    猜错原因比不写原因伤害更大 —— 读者一眼能看出来的错，最伤信任。
    """
    hits = []
    day = day_from
    while day <= day_to:
        for n in notes:
            reason = (n.get("reason") or "").strip()
            if reason and reason not in hits and _note_covers(n, day):
                hits.append(reason)
        day += timedelta(days=1)
    return "；".join(hits)


def _win_pct(record):
    """'4-2' -> 0.667。拿不到战绩返回 None，不拿 0 顶替。"""
    try:
        w, l = str(record).split("-")
        w, l = int(w), int(l)
    except (ValueError, AttributeError):
        return None
    return w / (w + l) if w + l else None


def focus_stars_by_team():
    """焦点球星按队归组，用于给明天的比赛加权和写看点。"""
    conf = load_json(FOCUS_FILE)
    out = {}
    for f in conf if isinstance(conf, list) else []:
        team = f.get("team") or ""
        name = f.get("cn") or f.get("en") or ""
        if team and name:
            out.setdefault(team, []).append(name)
    return out


def parse_preview(event):
    """明日赛程的轻量解析。不请求 summary —— 预告用不到球员数据。"""
    comp = (event.get("competitions") or [{}])[0]
    sides = {}
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        if side not in ("home", "away"):
            continue
        rec = ""
        for r in c.get("records") or []:
            if r.get("type") in ("total", None) and r.get("summary"):
                rec = r["summary"]
                break
        sides[side] = {
            "name_en": (c.get("team") or {}).get("displayName") or "",
            "team_id": str((c.get("team") or {}).get("id") or ""),
            "record": rec,
        }
    if len(sides) != 2:
        return None

    # 季后赛的系列赛大比分。常规赛那组 type=season 的不能要，理由见 parse_series
    season = event.get("season") or {}
    postseason = int(season.get("type") or 0) == 3 or "post" in str(season.get("slug") or "").lower()
    series = None
    for s in comp.get("series") or []:
        if (s.get("type") or "").lower() != "playoff":
            continue
        w = {str(x.get("id") or ""): int(x.get("wins") or 0) for x in (s.get("competitors") or [])}
        series = {
            "home": w.get(sides["home"]["team_id"], 0),
            "away": w.get(sides["away"]["team_id"], 0),
            "completed": bool(s.get("completed")),
        }
        postseason = True
        break

    national = []
    for b in comp.get("broadcasts") or []:
        if b.get("market") != "national":
            continue
        for n in b.get("names") or []:
            if n not in national:
                national.append(n)

    bj_dt = None
    iso = event.get("date")
    if iso:
        try:
            bj_dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BJ_TZ)
        except ValueError:
            bj_dt = None

    return {
        "id": event.get("id"),
        "away": sides["away"],
        "home": sides["home"],
        "national": national,
        "bj_dt": bj_dt,
        "postseason": postseason,
        "series": series,
        "cup": any("cup" in (n.get("headline") or "").lower() for n in (comp.get("notes") or [])),
    }


def pick_preview(previews, stars_by_team):
    """从明天的比赛里挑一场最值得看的。

    只用来回答「明天看哪场」，所以权重给「够不够分量」而不是「够不够胶着」——
    明天的胜负还没发生，没法算胶着。
    """
    best, best_score = None, None
    for pv in previews:
        pa, ph = _win_pct(pv["away"]["record"]), _win_pct(pv["home"]["record"])
        score = 0.0
        if pa is not None and ph is not None:
            score += (pa + ph) * 60                      # 两队都得赢球，分量才够
            score += max(0.0, 40 - abs(pa - ph) * 250)   # 战绩越接近，越可能好看
        if pv["national"]:
            score += 45                                  # 全美直播 = 联盟自己挑过的场次
        if pv["cup"]:
            score += 20
        stars = []
        for side in ("away", "home"):
            stars.extend(stars_by_team.get(pv[side]["name_en"], []))
        pv["stars"] = sorted(set(stars))
        score += 25 * len(pv["stars"])
        pv["_score"] = round(score, 1)
        if best_score is None or score > best_score:
            best, best_score = pv, score
    return best


# 读者点名要看的五支流量队，明日预告里优先给它们的场次
CORE_TEAMS = {
    "Golden State Warriors",
    "Los Angeles Lakers",
    "Philadelphia 76ers",
    "Houston Rockets",
    "San Antonio Spurs",
}


def watch_list(previews, pick, teams, limit=6):
    """明天这几支流量队的比赛。主推那场之外，其余的也要露面。

    只看队名不看人 —— 哪怕当家球星轮休，球队打了就值得提一句。
    五支点名队排前面，其他有焦点球员的队（比如开拓者）跟在后面。
    """
    out = []
    for pv in previews:
        if pv is pick:
            continue
        if not any(pv[s]["name_en"] in teams for s in ("away", "home")):
            continue
        bj = pv.get("bj_dt")
        out.append({
            "away": cn_team(pv["away"]["name_en"], TEAM_MAP),
            "home": cn_team(pv["home"]["name_en"], TEAM_MAP),
            "bj_date": date_cn(bj.date()) if bj else "",
            "bj_time": bj.strftime("%H:%M") if bj else "",
            "national": pv["national"],
            "core": any(pv[s]["name_en"] in CORE_TEAMS for s in ("away", "home")),
        })
    out.sort(key=lambda x: (0 if x["core"] else 1, x["bj_time"]))
    return out[:limit]


def preview_facts(pv):
    """推荐理由。每条都必须能从数据里复核，不吹。"""
    facts = []
    if pv["national"]:
        facts.append(f'{pv["national"][0]} 全美直播')
    if pv["cup"]:
        facts.append("NBA 杯小组赛")

    # 季后赛里常规赛战绩不是读者关心的东西，"6胜1负"这种推荐理由等于没说，
    # 换成系列赛大比分 —— 那才是决定这场有多要紧的数字。
    s = pv.get("series")
    if pv.get("postseason") and s:
        hw, aw = s.get("home") or 0, s.get("away") or 0
        if hw == 0 and aw == 0:
            facts.append("系列赛首战")
        elif hw == aw:
            facts.append(f"系列赛 {hw}-{aw} 打平")
        else:
            hi, lo = max(hw, aw), min(hw, aw)
            lead = cn_team(pv["home"]["name_en"], TEAM_MAP) if hw > aw else cn_team(pv["away"]["name_en"], TEAM_MAP)
            facts.append(f"{lead} {hi}-{lo} 领先" + ("，赢下就晋级" if hi == 3 else ""))
    else:
        pa, ph = _win_pct(pv["away"]["record"]), _win_pct(pv["home"]["record"])
        recs = f'{record_cn(pv["away"]["record"])} / {record_cn(pv["home"]["record"])}'
        if pa is not None and ph is not None:
            if abs(pa - ph) <= 0.06 and min(pa, ph) >= 0.45:
                facts.append(f"两队战绩咬在一起（{recs}）")
            elif min(pa, ph) >= 0.55:
                facts.append(f"两边都赢得多（{recs}）")

    if pv["stars"]:
        facts.append("、".join(pv["stars"]) + " 出战")
    return facts


def _pick_payload(pv):
    bj = pv.get("bj_dt")
    return {
        "away": cn_team(pv["away"]["name_en"], TEAM_MAP),
        "home": cn_team(pv["home"]["name_en"], TEAM_MAP),
        "away_record": pv["away"]["record"],
        "home_record": pv["home"]["record"],
        "bj_date": date_cn(bj.date()) if bj else "",
        "bj_time": bj.strftime("%H:%M") if bj else "",
        "national": pv["national"],
        "stars": pv["stars"],
        "postseason": bool(pv.get("postseason")),
        "facts": preview_facts(pv),
        "score": pv.get("_score", 0),
    }


def build_tomorrow(game_date):
    """明日看什么。三种结果：

    play      —— 明天有球，给一场焦点
    idle      —— 明天全联盟休战，说明原因 + 下一个比赛日是哪天
    offseason —— 两周内都没有比赛（真到休赛期了）
    """
    notes = load_idle_notes()
    stars_by_team = focus_stars_by_team()

    for i in range(1, LOOKAHEAD_DAYS + 1):
        day = game_date + timedelta(days=i)
        try:
            events = fetch_scoreboard(day)
        except Exception as e:
            print(f"  查 {day} 赛程失败（{e}），跳过")
            continue
        previews = [pv for pv in (parse_preview(e) for e in events) if pv]
        if not previews:
            continue

        pick = pick_preview(previews, stars_by_team)
        info = {
            "date": str(day),
            "date_cn": date_cn(day, with_weekday=True),
            "days_ahead": i,
            "total": len(previews),
            "postseason": any(pv.get("postseason") for pv in previews),
            "pick": _pick_payload(pick),
            "watch": watch_list(previews, pick, set(stars_by_team)),
        }
        if i == 1:
            info["status"] = "play"
            return info

        info["status"] = "idle"
        # 休战的是「明天」，不是下一个比赛日，两个日期要分开存
        idle_day = game_date + timedelta(days=1)
        info["idle_date"] = str(idle_day)
        info["idle_date_cn"] = date_cn(idle_day, with_weekday=True)
        info["reason"] = idle_reason(idle_day, day - timedelta(days=1), notes)
        info["idle_days"] = i - 1
        return info

    return {
        "status": "offseason",
        "date": "",
        "date_cn": "",
        "days_ahead": LOOKAHEAD_DAYS,
        "total": 0,
        "pick": None,
        "reason": "",
    }


# ---------------------------------------------------------------- 渲染层

FONT = "-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif"
COLOR_TEXT = "#1f1f1f"
COLOR_MUTED = "#8c8c8c"
COLOR_ACCENT = "#c2410c"
COLOR_LINE = "#ececec"

TEAM_MAP = {}
PLAYER_MAP = {}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sec_text(sec):
    """0.9 -> '0.9'，8.4 -> '8'，12.0 -> '12'。"""
    if sec < 1:
        return f"{sec:.1f}"
    if sec < 10:
        return f"{sec:.1f}".rstrip("0").rstrip(".")
    return str(int(round(sec)))


def clutch_text(g):
    """绝杀场的徽章与一句话说明。没有就返回 None。"""
    cl = (g.get("drama") or {}).get("clutch")
    if not cl:
        return None
    player = cn_player(cl.get("player_en"), PLAYER_MAP) if cl.get("player_en") else ""
    who = player or "他"
    # 没收录中文名的球员会显示英文，中英之间必须留空格，否则「Fears剩 7.3 秒」挤在一起
    gap = "" if (who and "\u4e00" <= who[-1] <= "\u9fff") else " "
    ot = "加时" if cl.get("overtime") else ""
    if cl["kind"] == "buzzer":
        badge = f"{ot}绝杀"
        detail = f"{who}{gap}压哨投进反超球"
    else:
        badge = f"{ot}准绝杀"
        detail = f"{who}{gap}剩 {_sec_text(cl['clock'])} 秒投进反超球，此后对手再没得分"
    return {"badge": badge, "detail": detail}


def _player_chip(p):
    """单人：名字深色加粗 + 得分橙色放大 + 板助缩小变灰，形成三级层次。"""
    name = cn_player(p["name"], PLAYER_MAP)

    extras = []
    if p.get("reb") not in ("", None, "0"):
        extras.append(f"{p['reb']}板")
    if p.get("ast") not in ("", None, "0"):
        extras.append(f"{p['ast']}助")
    extra_html = "".join(
        f'<span style="font-size:11px;line-height:2.0;color:#8f8f8f;'
        f'font-family:{FONT};padding-right:5px;">{esc(x)}</span>' for x in extras
    )

    return (
        # 整个「名字 分数 板助」包一层 nowrap：中文默认可以在任意字间断行，
        # 窄屏上出现过「字母哥」被拆成「字」和「母哥」两行，读起来像打错字。
        f'<span style="white-space:nowrap;">'
        f'<span style="font-size:13px;line-height:2.0;color:#2b2b2b;font-weight:700;'
        f'font-family:{FONT};">{esc(name)}</span>'
        f'<span style="font-size:16px;line-height:2.0;color:{COLOR_ACCENT};font-weight:700;'
        f'font-family:{FONT};padding:0 1px 0 2px;">{p["pts"]}</span>'
        f'<span style="font-size:12px;line-height:2.0;color:{COLOR_ACCENT};'
        f'font-family:{FONT};padding-right:6px;">分</span>'
        f'{extra_html}'
        f'</span>'
    )


def render_scorers_table(away_label, away_scorers, home_label, home_scorers):
    """两队得分手并成一张两行小表，队名独立成列，保证逐行左对齐。"""
    rows = []
    for label, scorers in ((away_label, away_scorers), (home_label, home_scorers)):
        if not scorers:
            continue
        sep = '<span style="font-size:11px;color:#d0d0d0;padding:0 6px;">·</span>'
        body = sep.join(_player_chip(p) for p in scorers)
        rows.append(
            '<tr>'
            f'<td style="width:19%;text-align:right;vertical-align:top;padding:2px 9px 0 0;'
            f'font-size:11px;line-height:2.0;color:#a8a8a8;font-family:{FONT};">{esc(label)}</td>'
            f'<td style="width:81%;vertical-align:top;padding:2px 0;">{body}</td>'
            '</tr>'
        )
    if not rows:
        return ""
    return (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
        f'margin:6px 0 0 0;font-family:{FONT};">{"".join(rows)}</table>'
    )


def render_folded(games):
    """被折叠的场次：只留一行比分，不占版面。

    只出现在一天场次超过 MAX_DETAIL 的时候（常规赛收官日、或者赛季初的超级比赛日）。
    """
    rows = []
    for g in games:
        home, away = g["home"], g["away"]
        hs, as_ = home["score"], away["score"]
        hw = hs is not None and as_ is not None and hs > as_
        aw = hs is not None and as_ is not None and as_ > hs
        a_sty = f"color:{COLOR_TEXT};font-weight:bold;" if aw else "color:#a8a8a8;"
        h_sty = f"color:{COLOR_TEXT};font-weight:bold;" if hw else "color:#a8a8a8;"
        rows.append(
            f'<div style="font-size:12px;line-height:2.0;font-family:{FONT};">'
            f'<span style="{a_sty}">{esc(cn_team(away["name_en"], TEAM_MAP))}</span>'
            f'<span style="color:{COLOR_ACCENT};padding:0 6px;">'
            f'{esc(as_ if as_ is not None else "-")}-{esc(hs if hs is not None else "-")}</span>'
            f'<span style="{h_sty}">{esc(cn_team(home["name_en"], TEAM_MAP))}</span>'
            f'</div>'
        )
    return (
        '<div style="margin:24px 0 0;padding:14px 16px;background:#fafafa;">'
        f'<div style="font-size:11px;color:#b0b0b0;letter-spacing:1px;margin-bottom:4px;'
        f'font-family:{FONT};">另外 {len(games)} 场</div>'
        + "".join(rows) + "</div>"
    )


def render_game(g, label_key=None, highlight=None, watch_note=None):
    home, away = g["home"], g["away"]
    hs, as_ = home["score"], away["score"]
    home_win = hs is not None and as_ is not None and hs > as_
    away_win = hs is not None and as_ is not None and as_ > hs

    def side_style(is_winner, align):
        return (
            f"font-size:15px;line-height:1.4;text-align:{align};padding:2px 0;"
            f"color:{COLOR_TEXT if is_winner else '#6b6b6b'};"
            f"font-weight:{'bold' if is_winner else 'normal'};"
        )

    def score_style(is_winner):
        return (
            f"font-size:24px;line-height:1.2;text-align:center;padding:2px 0;"
            f"color:{COLOR_TEXT if is_winner else '#a8a8a8'};font-weight:bold;"
        )

    parts = []

    # 绝杀 / 准绝杀：整篇里最该被看见的一行，所以单独用深红徽章压在队名上方
    clutch = clutch_text(g)
    badges = []
    if clutch:
        badges.append(
            f'<span style="display:inline-block;font-size:11px;line-height:1.6;color:#ffffff;'
            f'background:#b91c1c;padding:2px 9px;letter-spacing:1px;font-weight:bold;'
            f'margin-right:5px;font-family:{FONT};">{esc(clutch["badge"])}</span>'
        )
    if label_key in LABELS:
        text, color = LABELS[label_key]
        badges.append(
            f'<span style="display:inline-block;font-size:11px;line-height:1.6;color:#ffffff;'
            f'background:{color};padding:2px 9px;letter-spacing:1px;margin-right:5px;'
            f'font-family:{FONT};">{text}</span>'
        )
    if badges:
        detail = (
            f'<span style="font-size:11px;color:#b91c1c;padding-left:8px;font-family:{FONT};">'
            f'{esc(clutch["detail"])}</span>' if clutch else ""
        )
        parts.append(
            f'<div style="margin:0 0 8px 0;">{"".join(badges)}{detail}</div>'
        )
    elif watch_note:
        # 排进推荐区但没有抢到标签的场次，用一句话交代它凭什么排前面。
        # 有标签的不写，否则「今日最大逆转」下面再挂「落后 17 分翻盘」就是同一句话说两遍。
        parts.append(
            f'<div style="margin:0 0 8px 0;font-size:11px;color:{COLOR_ACCENT};'
            f'letter-spacing:1px;font-family:{FONT};">值得看 · {esc(watch_note)}</div>'
        )

    # 顶部队名 + 比分
    parts.append(f'''
<table style="width:100%;border-collapse:collapse;table-layout:fixed;margin:0;font-family:{FONT};">
  <tr>
    <td style="{side_style(away_win, 'right')}width:36%;">{esc(cn_team(away["name_en"], TEAM_MAP))}</td>
    <td style="{score_style(away_win)}width:12%;">{esc(as_ if as_ is not None else '-')}</td>
    <td style="width:5%;text-align:center;font-size:11px;color:#dcdcdc;">:</td>
    <td style="{score_style(home_win)}width:12%;">{esc(hs if hs is not None else '-')}</td>
    <td style="{side_style(home_win, 'left')}width:36%;">{esc(cn_team(home["name_en"], TEAM_MAP))}</td>
  </tr>
</table>''')

    # 系列赛大比分：季后赛里读者第一个想知道的数字，压在比分正下方
    st = series_text(g)
    if st:
        parts.append(
            f'<div style="text-align:center;font-size:12px;color:{COLOR_ACCENT};'
            f'letter-spacing:1px;margin:4px 0 0;font-family:{FONT};">{esc(st)}</div>'
        )

    # 单节比分
    al, hl = away["lines"], home["lines"]
    overtimes = max(0, max(len(al), len(hl)) - 4)
    if al and hl and len(al) >= 4 and len(hl) >= 4:
        n = max(len(al), len(hl))
        label_w = "16%" if n > 4 else "20%"
        cell_w = f"{(84 / n) if n > 4 else 20:.1f}%"

        # 列标签单列一行：第 5 节起是加时，不标出来读者会以为多了个数字
        head_cells = [
            f'<td style="width:{label_w};padding:0 0 1px;"></td>'
        ]
        for i in range(n):
            tag = str(i + 1) if i < 4 else ("OT" if i == 4 else f"OT{i - 3}")
            head_cells.append(
                f'<td style="width:{cell_w};text-align:center;padding:0 0 1px;font-size:10px;'
                f'color:#cdcdcd;font-family:{FONT};">{tag}</td>'
            )

        cells = [
            f'<td style="width:{label_w};text-align:left;padding:2px 0;font-size:11px;'
            f'color:#c4c4c4;font-family:{FONT};">分节</td>'
        ]
        for i in range(n):
            a = al[i] if i < len(al) and al[i] is not None else "-"
            h = hl[i] if i < len(hl) and hl[i] is not None else "-"
            cells.append(
                f'<td style="width:{cell_w};text-align:center;padding:2px 0;font-size:11px;'
                f'color:{COLOR_MUTED};font-family:{FONT};">{a}-{h}</td>'
            )
        parts.append(
            f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;margin:1px 0 0 0;">'
            f'<tr>{"".join(head_cells)}</tr><tr>{"".join(cells)}</tr></table>'
        )

    # 加时标记：比分本身看不出打了几个加时
    if overtimes:
        parts.append(
            f'<div style="text-align:center;font-size:10px;color:{COLOR_ACCENT};'
            f'letter-spacing:2px;margin:5px 0 0;font-family:{FONT};">'
            f'{"经过 " + str(overtimes) + " 个加时" if overtimes > 1 else "加时赛"}</div>'
        )

    # 分差走势图
    if g.get("chart"):
        home_cn = cn_team(home["name_en"], TEAM_MAP)
        away_cn = cn_team(away["name_en"], TEAM_MAP)
        parts.append(
            f'<div style="margin:10px 0 2px;">'
            f'<img src="{esc(g["chart"])}" style="width:100%;display:block;border:0;" alt="比分走势">'
            f'<div style="font-size:12px;line-height:1.9;color:#9a9a9a;margin-top:6px;'
            f'font-family:{FONT};">'
            f'<span style="display:inline-block;width:16px;height:3px;background:{CHART_AWAY_HEX};'
            f'vertical-align:middle;margin-right:6px;"></span>'
            f'<span style="color:{CHART_AWAY_HEX};font-weight:600;">{esc(away_cn)}</span>'
            f'<span style="display:inline-block;width:16px;height:3px;background:{CHART_HOME_HEX};'
            f'vertical-align:middle;margin:0 6px 0 16px;"></span>'
            f'<span style="color:{CHART_HOME_HEX};font-weight:600;">{esc(home_cn)}</span>'
            f'<span style="margin-left:14px;color:#c8c8c8;font-size:11px;">横轴为比赛进程</span>'
            f'</div>'
            f'</div>'
        )

    # 看点
    hook = build_hook(g, label_key == "drama")
    if hook:
        parts.append(
            f'<div style="font-size:13px;line-height:1.8;color:#5a5a5a;margin:8px 0 4px;font-family:{FONT};">'
            f'{esc(hook)}</div>'
        )

    # 球员
    parts.append(render_scorers_table(
        cn_team(away["name_en"], TEAM_MAP), g["scorers"]["away"],
        cn_team(home["name_en"], TEAM_MAP), g["scorers"]["home"],
    ))

    # 球队关键数据
    hstat, astat = home["stats"], away["stats"]
    if hstat.get("fieldGoalPct") or astat.get("fieldGoalPct"):
        def stat_line(t):
            s = home if t == "h" else away
            fg = s["stats"].get("fieldGoalPct", "-")
            tp = s["stats"].get("threePointFieldGoalPct", "-")
            rb = s["stats"].get("totalRebounds", "-")
            at = s["stats"].get("assists", "-")
            to = s["stats"].get("totalTurnovers", s["stats"].get("turnovers", "-"))
            return f'<td style="text-align:center;font-size:11px;color:{COLOR_MUTED};padding:4px 2px;font-family:{FONT};">{fg}</td><td style="text-align:center;font-size:11px;color:{COLOR_MUTED};padding:4px 2px;font-family:{FONT};">{tp}</td><td style="text-align:center;font-size:11px;color:{COLOR_MUTED};padding:4px 2px;font-family:{FONT};">{rb}</td><td style="text-align:center;font-size:11px;color:{COLOR_MUTED};padding:4px 2px;font-family:{FONT};">{at}</td><td style="text-align:center;font-size:11px;color:{COLOR_MUTED};padding:4px 2px;font-family:{FONT};">{to}</td>'

        parts.append(f'''
<table style="width:100%;border-collapse:collapse;table-layout:fixed;margin:8px 0 0;background:#fafafa;">
  <tr>
    <td style="width:24%;"></td>
    <td style="text-align:center;font-size:10px;color:#b0b0b0;padding:4px 2px;">命中率</td>
    <td style="text-align:center;font-size:10px;color:#b0b0b0;padding:4px 2px;">三分</td>
    <td style="text-align:center;font-size:10px;color:#b0b0b0;padding:4px 2px;">篮板</td>
    <td style="text-align:center;font-size:10px;color:#b0b0b0;padding:4px 2px;">助攻</td>
    <td style="text-align:center;font-size:10px;color:#b0b0b0;padding:4px 2px;">失误</td>
  </tr>
  <tr>
    <td style="font-size:11px;color:#7a7a7a;padding:4px 0 4px 6px;font-family:{FONT};">{esc(cn_team(away["name_en"], TEAM_MAP))}</td>
    {stat_line("a")}
  </tr>
  <tr>
    <td style="font-size:11px;color:#7a7a7a;padding:0 0 5px 6px;font-family:{FONT};">{esc(cn_team(home["name_en"], TEAM_MAP))}</td>
    {stat_line("h")}
  </tr>
</table>''')

    meta = []
    if g.get("tipoff_bj"):
        meta.append(f"北京 {g['tipoff_bj']} 开球")
    # 季后赛 ESPN 给的 record 就是系列赛战绩，比分上面那行已经写了，这里重复反而糊
    if not g.get("series"):
        if away.get("record"):
            meta.append(f"{cn_team(away['name_en'], TEAM_MAP)} {away['record']}")
        if home.get("record"):
            meta.append(f"{cn_team(home['name_en'], TEAM_MAP)} {home['record']}")
    if meta:
        parts.append(
            f'<div style="font-size:11px;color:#c0c0c0;margin-top:6px;font-family:{FONT};">'
            f'{" ｜ ".join(esc(m) for m in meta)}</div>'
        )

    # 高光挂在这场自己的卡片里，读者不用回头找
    if highlight:
        parts.append(render_best_action(g, highlight))

    return (
        '<div style="margin:0 0 22px 0;padding:0 0 20px 0;border-bottom:1px solid '
        f'{COLOR_LINE};">' + "".join(parts) + "</div>"
    )


def record_cn(rec):
    """'4-2' -> '4胜2负'。战绩的短横线写法对内行清楚，对普通读者是黑话。"""
    try:
        w, l = str(rec).split("-")
        return f"{int(w)}胜{int(l)}负"
    except (ValueError, AttributeError):
        return str(rec or "")


ACTION_CN = {"alley": "空中接力扣篮", "dunk": "扣篮", "block": "封盖", "three": "三分"}


def player_label(name_en, team_en):
    """有中文名就用中文名；没有就在姓氏前补队名 —— 单个高光里只出现一个姓氏太容易认错人。"""
    if not name_en:
        return cn_team(team_en, TEAM_MAP)
    hit = PLAYER_MAP.get(normalize_name(name_en))
    if hit:
        return hit
    return f"{cn_team(team_en, TEAM_MAP)} {cn_player(name_en, PLAYER_MAP)}"


def render_best_action(g, a):
    """今日最佳一球。挂在它所属的那场比赛下面，读者不用回头找是哪一场。

    措辞刻意不写「十佳球」—— NBA 官方那份榜单没有逐场接口，
    这里是自己按动作类型和时间点挑的，写清楚来源才不会被读者当成官方口径。
    """
    if not a:
        return ""
    player = player_label(a.get("player_en"), g[a["side"]]["name_en"])
    if a["kind"] == "clutch":
        what = f"{player} 压哨绝杀" if (a.get("clock") or 0) <= 1 else f"{player} 准绝杀"
    elif a["kind"] == "three" and a.get("dist"):
        what = f'{player} {a["dist"]} 英尺三分'
    else:
        what = f'{player} {ACTION_CN.get(a["kind"], "好球")}'

    clock = a.get("clock")
    if a["kind"] == "clutch":
        when = "加时" if a["period"] > 4 else "第四节结束"
    elif clock is not None and clock <= 1:
        when = "压哨"
    elif a["period"] > 4:
        when = f'加时 剩 {fmt_clock(clock)}'
    else:
        when = f'第 {a["period"]} 节 剩 {fmt_clock(clock)}'

    away_cn = cn_team(g["away"]["name_en"], TEAM_MAP)
    home_cn = cn_team(g["home"]["name_en"], TEAM_MAP)
    line = f'{away_cn} {g["away"]["score"]}-{g["home"]["score"]} {home_cn} · {when}'

    return (
        '<div style="margin:16px 0 0;padding:13px 15px;background:#fdf6f0;'
        f'border-left:3px solid {COLOR_ACCENT};">'
        f'<div style="font-size:11px;color:{COLOR_ACCENT};letter-spacing:2px;'
        f'font-family:{FONT};">今日最佳一球</div>'
        f'<div style="font-size:16px;font-weight:bold;color:{COLOR_TEXT};margin-top:5px;'
        f'line-height:1.5;font-family:{FONT};">{esc(what)}</div>'
        f'<div style="font-size:11px;color:#9a9a9a;margin-top:3px;font-family:{FONT};">'
        f'{esc(line)}</div>'
        f'</div>'
    )


def render_tomorrow(info):
    """末尾的「明日看什么」。有球就推一场，没球就说清为什么、下回是哪天。"""
    if not info:
        return ""

    head = (
        f'<div style="font-size:12px;color:{COLOR_ACCENT};letter-spacing:2px;'
        f'margin-bottom:8px;font-family:{FONT};">明日焦点</div>'
    )
    wrap_open = (
        '<div style="margin:28px 0 0;padding:20px 0 0;border-top:1px solid #ececec;">'
    )
    wrap_close = "</div>"

    # 两周内都没球：真到休赛期了
    if info.get("status") == "offseason":
        return (
            wrap_open + head +
            f'<div style="font-size:14px;line-height:1.9;color:#1f1f1f;font-family:{FONT};">'
            f'未来两周联盟都没有排赛，赛季已经结束或还没开打，下一份战报等有新比赛再更新。'
            f'</div>' + wrap_close
        )

    pick = info.get("pick") or {}
    if not pick:
        return ""

    # 焦点场次（休战时的「下一个比赛日」也复用它）
    def pick_block():
        rec_a, rec_h = record_cn(pick.get("away_record")), record_cn(pick.get("home_record"))
        # 季后赛的常规赛战绩没有参考价值，系列赛比分已经写进 facts 里了
        recs = "" if pick.get("postseason") else " / ".join(x for x in (rec_a, rec_h) if x)
        meta = []
        if pick.get("bj_date"):
            meta.append(f'北京时间 {pick["bj_date"]} {pick.get("bj_time", "")}'.strip())
        meta.append(f'{pick["home"]}主场')
        facts = "；".join(pick.get("facts") or [])
        return (
            f'<div style="font-size:16px;font-weight:bold;color:{COLOR_TEXT};line-height:1.5;'
            f'font-family:{FONT};">'
            f'{esc(pick["away"])}'
            f'<span style="color:#d4d4d4;font-weight:normal;padding:0 6px;">@</span>'
            f'{esc(pick["home"])}'
            f'</div>'
            f'<div style="font-size:11px;color:#a8a8a8;margin-top:3px;font-family:{FONT};">'
            f'{" ｜ ".join(esc(m) for m in meta)}</div>'
            + (f'<div style="font-size:13px;line-height:1.8;color:#5a5a5a;margin-top:5px;'
               f'font-family:{FONT};">{esc(facts)}</div>' if facts else "")
            + (f'<div style="font-size:11px;color:#c4c4c4;margin-top:3px;font-family:{FONT};">'
               f'战绩 {esc(recs)}</div>' if recs else "")
        )

    # 流量队的其他场次：主推只有一场，但这几队的比赛读者可能都想看
    def watch_block():
        watch = info.get("watch") or []
        if not watch:
            return ""
        rows = "".join(
            f'<div style="font-size:12px;color:#6b6b6b;line-height:2.0;font-family:{FONT};">'
            f'{esc(w["away"])}<span style="color:#d8d8d8;padding:0 5px;">@</span>'
            f'{esc(w["home"])}'
            f'<span style="font-size:11px;color:#b8b8b8;padding-left:9px;">'
            f'北京时间 {esc(w["bj_date"])} {esc(w["bj_time"])}</span>'
            f'</div>'
            for w in watch
        )
        return (
            '<div style="margin-top:12px;padding-top:9px;border-top:1px dashed #ededed;">'
            f'<div style="font-size:11px;color:#b0b0b0;letter-spacing:1px;margin-bottom:1px;'
            f'font-family:{FONT};">另外这几场</div>'
            f'{rows}</div>'
        )

    # 明天就打
    if info.get("status") == "play":
        tail = (
            f"{info['total']} 场季后赛，这是最值得定闹钟的一场"
            if info.get("postseason")
            else f"全联盟 {info['total']} 场，这是最值得定闹钟的一场"
        )
        return (
            wrap_open + head + pick_block() + watch_block() +
            f'<div style="font-size:11px;color:#c4c4c4;margin-top:8px;font-family:{FONT};">'
            f'明天{tail}</div>'
            + wrap_close
        )

    # 明天休战
    reason = info.get("reason") or ""
    day_cn = info.get("idle_date_cn") or info.get("date_cn") or ""
    explain = (
        f'美国时间 {esc(day_cn)} 全联盟没有比赛'
        + (f' —— {esc(reason)}' if reason else "，联盟当天没有排赛")
        + "。"
    )
    return (
        wrap_open +
        f'<div style="font-size:12px;color:#9a9a9a;letter-spacing:2px;margin-bottom:8px;'
        f'font-family:{FONT};">明日休战</div>'
        f'<div style="font-size:14px;line-height:1.9;color:{COLOR_TEXT};font-family:{FONT};">'
        f'{explain}</div>'
        f'<div style="font-size:12px;color:#8c8c8c;margin-top:12px;letter-spacing:1px;'
        f'font-family:{FONT};">下一个比赛日 · {esc(info["date_cn"])}</div>'
        f'<div style="margin-top:6px;">{pick_block()}</div>'
        f'{watch_block()}'
        f'<div style="font-size:11px;color:#c4c4c4;margin-top:8px;font-family:{FONT};">'
        f'那天{"全联盟 " if not info.get("postseason") else ""}{info["total"]} 场'
        f'{"季后赛" if info.get("postseason") else ""}</div>'
        + wrap_close
    )


def render_page(games, game_date, display_date, tomorrow=None):
    played = [g for g in games if g.get("finished")]
    total = len(played)
    labels = assign_labels(played)

    # 推荐比赛要跳过导语讲的那一场，否则同一场在页首出现两次
    head = pick_headline(played)
    head_id = head["id"] if head else None

    best = pick_best_action(played)
    best_id = best[0]["id"] if best else None
    best_act = best[1] if best else None

    if total:
        # 版面顺序：值得看的排前面，标题那场放第一个；其余按开球时间跟在后面。
        # 不再单独做一份「其它推荐比赛」的行式清单——同一场比赛在页面上
        # 出现两次，读者会觉得你在凑篇幅。
        picks = pick_watchable(played, head_id)
        reasons = {g["id"]: r for g, r in picks}
        if head:
            reasons[head["id"]] = watch_reason(
                head, abs(head["home"]["score"] - head["away"]["score"])
            )

        feat_ids = []
        for i in ([head_id] if head_id else []) + [g["id"] for g, _ in picks]:
            if i and i not in feat_ids:
                feat_ids.append(i)
        feat_set = set(feat_ids)
        by_id = {g["id"]: g for g in played}
        featured = [by_id[i] for i in feat_ids if i in by_id]   # 标题场 + 推荐场，按好看程度
        others = [g for g in played if g["id"] not in feat_set]  # 其余按开球时间

        # 常规赛收官日会让 30 队同一天打完，全展开页面长度翻倍。超过上限时
        # 先保证推荐场都在，剩下的名额按时间顺序给其余场次，多出来的压成一行。
        ordered = featured + others
        detail, folded = ordered[:MAX_DETAIL], ordered[MAX_DETAIL:]
        detail_ids = {g["id"] for g in detail}
        feat_detail = [g for g in featured if g["id"] in detail_ids]
        other_detail = [g for g in others if g["id"] in detail_ids]

        # 最平淡兜底：其余场次里挑一场标出来，让读者知道哪场可以跳过。
        # assign_labels 的条件偏严（分差上双 + 末节几乎没缠斗），有些日子
        # 一场都挑不出来；那样读者就完全看不出哪场不值得点开。
        if other_detail and "flat" not in labels.values():
            cand = [
                g for g in other_detail
                if g["id"] not in labels
                and abs(g["home"]["score"] - g["away"]["score"]) >= 8
            ]
            if cand:
                worst = min(cand, key=lambda g: (g.get("drama") or {}).get("score") or 0)
                labels[worst["id"]] = "flat"

        blocks = ""
        if feat_detail:
            blocks += render_section("推荐比赛", f"{len(feat_detail)} 场")
            blocks += "".join(
                render_game(
                    g, labels.get(g["id"]),
                    best_act if g["id"] == best_id else None,
                    reasons.get(g["id"]),
                )
                for g in feat_detail
            )
        if other_detail:
            blocks += render_section(
                f"其余 {len(other_detail)} 场", "按开球时间", top=34
            )
            blocks += "".join(
                render_game(g, labels.get(g["id"]), best_act if g["id"] == best_id else None)
                for g in other_detail
            )
        if folded:
            blocks += render_folded(folded)
    else:
        pending = [g for g in games if not g.get("finished")]
        if pending:
            blocks = (
                f'<div style="padding:36px 0;text-align:center;font-size:14px;color:{COLOR_MUTED};'
                f'font-family:{FONT};">今日 {len(pending)} 场尚未结束，稍后重试</div>'
            )
        else:
            blocks = (
                f'<div style="padding:36px 0;text-align:center;font-size:14px;color:{COLOR_MUTED};'
                f'font-family:{FONT};">今天没有比赛</div>'
            )

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>去球吧 · {esc(display_date)} 战报</title>
</head>
<body style="margin:0;padding:0;background:#fafafa;">

<div style="max-width:640px;margin:0 auto;padding:30px 20px 44px;background:#ffffff;font-family:{FONT};">

  <div style="font-size:12px;color:{COLOR_ACCENT};letter-spacing:1px;margin-bottom:6px;">去球吧<span style="color:#b8b8b8;padding:0 6px;">·</span>NBA 每日战报</div>
  <div style="font-size:24px;font-weight:bold;color:{COLOR_TEXT};margin-bottom:4px;">{esc(display_date)}<span style="font-size:12px;font-weight:normal;color:#a0a0a0;padding-left:7px;">美国时间</span></div>
  <div style="font-size:13px;color:{COLOR_MUTED};margin-bottom:24px;">共 {total} 场 ｜ 每行格式：客队 比分 : 比分 主队</div>

  <div style="font-size:15px;line-height:1.9;color:{COLOR_TEXT};background:#fdf6f0;border-left:3px solid {COLOR_ACCENT};padding:14px 16px;margin-bottom:22px;">
    <div>{esc(build_lead(games))}</div>
  </div>

  {render_focus(build_focus(games))}

  {blocks}

  {render_tomorrow(tomorrow)}

  <div style="font-size:12px;color:#b0b0b0;line-height:1.8;margin-top:6px;">
    <span style="color:{COLOR_ACCENT};">去球吧</span> ｜ 每天一份 NBA 战报，只写场上发生的事<br>
    本文基于公开赛事数据独立撰写，与 NBA 及任何转播平台无关联。<br>
    比赛日 {esc(game_date)}（美国时间）｜ 数据来源：ESPN
  </div>

</div>
</body>
</html>
'''


# ---------------------------------------------------------------- 主流程

def collect(game_date):
    """返回解析好的比赛列表。ESPN 失败时退回 balldontlie 比分。"""
    try:
        events = fetch_scoreboard(game_date)
        print(f"  ESPN 记分板：{len(events)} 场")
    except Exception as e:
        print(f"  ESPN 记分板失败（{e}），改用 balldontlie 兜底")
        return fetch_scores_bdl(game_date)

    games = []
    for idx, ev in enumerate(events, 1):
        g = parse_event(ev, TEAM_MAP)
        if not g:
            continue
        try:
            g = enrich_with_summary(g, fetch_summary(g["id"]), TEAM_MAP)
        except Exception as e:
            print(f"  ({idx}/{len(events)}) 详情获取失败，仅保留比分：{e}")
        games.append(g)
        if g["finished"]:
            print(f"  ({idx}/{len(events)}) {cn_team(g['away']['name_en'], TEAM_MAP)} "
                  f"{g['away']['score']} - {g['home']['score']} "
                  f"{cn_team(g['home']['name_en'], TEAM_MAP)}")
    return games


def main():
    global TEAM_MAP, PLAYER_MAP

    game_date = resolve_game_date()
    TEAM_MAP = load_json(TEAMS_FILE)
    PLAYER_MAP = {normalize_name(k): v for k, v in load_json(PLAYERS_FILE).items()}

    print(f"[1/5] 比赛日：{game_date}（美国时间）")
    print("[2/5] 拉取比赛与详情")
    games = collect(game_date)

    print("[3/5] 生成分差走势图")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made = 0
    for g in games:
        series = (g.get("drama") or {}).get("series") or []
        if not series:
            continue
        rel = f"charts/{g['id']}.png"
        try:
            score_chart(series, OUT_DIR / rel)
            g["chart"] = rel
            made += 1
        except Exception as e:  # 图挂了不能影响出稿
            print(f"  场次 {g['id']} 走势图生成失败：{e}")
    print(f"  共 {made} 张")

    # 清掉历史遗留的图，避免仓库里越堆越多
    keep = {f"{g['id']}.png" for g in games if g.get("chart")}
    for f in (OUT_DIR / "charts").glob("*.png"):
        if f.name not in keep:
            f.unlink()

    print("[4/5] 查明日赛程")
    try:
        tomorrow = build_tomorrow(game_date)
        if tomorrow.get("status") == "play":
            p = tomorrow["pick"]
            print(f'  明天 {p["away"]} @ {p["home"]}（{tomorrow["total"]} 场）')
        elif tomorrow.get("status") == "idle":
            print(f'  明天休战，下一比赛日 {tomorrow["date_cn"]}')
        else:
            print("  两周内都没有比赛")
    except Exception as e:   # 预告拿不到不该影响整篇战报
        print(f"  明日赛程获取失败：{e}")
        tomorrow = None

    print("[5/5] 生成 HTML")
    html = render_page(games, game_date, game_date, tomorrow)
    out_path = OUT_DIR / "report.html"
    out_path.write_text(html, encoding="utf-8")

    finished = [g for g in games if g.get("finished")]
    headline = pick_headline(finished)
    labels = assign_labels(finished)
    best = pick_best_action(finished)
    # 封面图用头条那场：队名、比分、两队官方主色（ESPN 的 team.color）
    cover = None
    cover_g = headline or (finished[0] if finished else None)
    if cover_g:
        y, mo, dd = str(game_date).split("-")
        tag = LABELS[labels[cover_g["id"]]][0] if cover_g["id"] in labels else ""
        cover = {
            "date": f"{int(y)}年{int(mo)}月{int(dd)}日",
            "away": cn_team(cover_g["away"]["name_en"], TEAM_MAP),
            "away_score": cover_g["away"]["score"],
            "away_color": cover_g["away"].get("color") or "",
            "home": cn_team(cover_g["home"]["name_en"], TEAM_MAP),
            "home_score": cover_g["home"]["score"],
            "home_color": cover_g["home"].get("color") or "",
            "footer": (
                f"{len(finished)} 场季后赛" if any(g.get("postseason") for g in finished)
                else f"全联盟 {len(finished)} 场"
            ) + f"|{tag}",
        }
    summary = {
        "game_date": str(game_date),
        "generated_at": datetime.now(BJ_TZ).isoformat(timespec="seconds"),
        "total_games": len(finished),
        "postseason": any(g.get("postseason") for g in finished),
        "headline": (
            f'{cn_team(headline["away"]["name_en"], TEAM_MAP)} '
            f'{headline["away"]["score"]}-{headline["home"]["score"]} '
            f'{cn_team(headline["home"]["name_en"], TEAM_MAP)}'
        ) if headline else None,
        "lead": build_lead(games),
        "focus": build_focus(finished),
        "cover": cover,
        "best_action": ({
            "player": cn_player(best[1]["player_en"], PLAYER_MAP) if best[1].get("player_en") else None,
            "kind": best[1]["kind"],
            "dist_ft": best[1].get("dist"),
            "period": best[1]["period"],
            "clock_sec": best[1].get("clock"),
            "game": f'{cn_team(best[0]["away"]["name_en"], TEAM_MAP)} '
                    f'{best[0]["away"]["score"]}-{best[0]["home"]["score"]} '
                    f'{cn_team(best[0]["home"]["name_en"], TEAM_MAP)}',
        } if best else None),
        "tomorrow": tomorrow,
        "games": [{
            "away": cn_team(g["away"]["name_en"], TEAM_MAP),
            "home": cn_team(g["home"]["name_en"], TEAM_MAP),
            "away_score": g["away"]["score"],
            "home_score": g["home"]["score"],
            "label": LABELS[labels[g["id"]]][0] if g["id"] in labels else None,
            "series": series_text(g),
            # 加时数：单节比分表长度 - 4。头条素材里「加时」是个强钩子，单独存一份
            "overtimes": max(
                0,
                max(len(g["home"].get("lines") or []), len(g["away"].get("lines") or [])) - 4,
            ),
            "hook": build_hook(g, labels.get(g["id"]) == "drama"),
            "drama": {
                "lead_changes": (g.get("drama") or {}).get("lead_changes", 0),
                "ties": (g.get("drama") or {}).get("ties", 0),
                "comeback": (g.get("drama") or {}).get("comeback", 0),
                "close_seconds_q4": (g.get("drama") or {}).get("close_seconds", 0),
                "score": (g.get("drama") or {}).get("score", 0),
                "clutch": (g.get("drama") or {}).get("clutch"),
            },
        } for g in finished],
    }
    (OUT_DIR / "latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[5/5] 完成：{out_path}")
    print(f"      {OUT_DIR / 'latest.json'}（{len(finished)} 场）")

    # 封面图是附加产物：没有 Pillow 或中文字体就跳过，绝不能因此让战报出不来
    try:
        import cover as cover_mod
        cover_mod.build()
    except Exception as e:
        print(f"  封面图跳过：{e}")

    # 今日主打同理：从当天挑一场，出公众号次条 + 头条号两用的写作稿，失败不影响战报
    try:
        import export_feature
        export_feature.main()
    except Exception as e:
        print(f"  今日主打跳过：{e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"失败：{exc}", file=sys.stderr)
        sys.exit(1)
