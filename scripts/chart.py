#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
零依赖的极简 PNG 生成器 —— 用来画「比分随时间」的双折线图。

为什么不引入 matplotlib：
  1. 不想给 GitHub Actions 增加安装步骤；
  2. CI 里没有中文字体，图上照样是方块；
  3. 图里不需要文字，队名与配色说明交给 HTML 写，所以手写像素足够。

输出为 RGB PNG（无 alpha），2 倍尺寸输出、CSS 缩到一半，手机上不糊。
"""

import bisect
import struct
import zlib
from pathlib import Path

HOME_LINE = (194, 65, 12)      # 主队：砖红，与正文强调色同源
AWAY_LINE = (29, 111, 165)     # 客队：蓝
HOME_HEX = "#%02x%02x%02x" % HOME_LINE
AWAY_HEX = "#%02x%02x%02x" % AWAY_LINE
GRID = (234, 234, 234)
PERIOD_LINE = (232, 232, 232)
BASELINE = (208, 208, 208)
BG = (255, 255, 255)
FILL_ALPHA = 0.26              # 领先区填充的不透明度（越大越实）


def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path, width, height, rows):
    """rows：每行一个 bytearray，长度 = width * 3（RGB）。"""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(png)




def _blend(canvas, w, x, y, rgb, alpha):
    """把 rgb 以 alpha 不透明度叠到已有像素上。用它填充才不会盖掉网格线。"""
    if 0 <= y < len(canvas) and 0 <= x < w:
        i = x * 3
        row = canvas[y]
        for k in range(3):
            row[i + k] = int(round(row[i + k] * (1 - alpha) + rgb[k] * alpha))


def _px(canvas, w, x, y, rgb):
    if 0 <= y < len(canvas) and 0 <= x < w:
        i = x * 3
        row = canvas[y]
        row[i], row[i + 1], row[i + 2] = rgb


def _thick(canvas, w, x, y0, y1, rgb, half=1):
    """在 x 列上把 y0..y1 画成一段有粗细的线（竖向连通，避免陡坡断线）。"""
    if y0 > y1:
        y0, y1 = y1, y0
    for y in range(y0, y1 + 1):
        for dx in range(-half, half + 1):
            _px(canvas, w, x + dx, y, rgb)


def score_chart(series, out_path, width=1200, height=400,
                period_marks=(720, 1440, 2160)):
    """series: [(elapsed_seconds, home_score, away_score), ...]，按时间升序。

    两条累计得分曲线：橙 = 主队，蓝 = 客队。纵轴 0→最高分，横轴为比赛进程。
    """
    if not series:
        return None

    total = max(t for t, _, _ in series) or 1
    peak = max(max(h, a) for _, h, a in series) or 1
    top = max(20, (int(peak) // 20 + 1) * 20)   # 纵轴取到 20 的整数倍，留余量

    pad_t, pad_b = 14, 12
    usable = height - pad_t - pad_b

    rows = [bytearray(BG * width) for _ in range(height)]

    def y_of(score):
        return int(round(height - pad_b - (score / top) * usable))

    # 横向网格线（每 20 分一格）
    step = 20
    while step < top:
        gy = y_of(step)
        for x in range(width):
            _px(rows, width, x, gy, GRID)
        step += 20

    # 节间分隔线
    for mark in period_marks:
        if mark < total:
            x = int(mark / total * (width - 1))
            for y in range(pad_t, height - pad_b):
                _px(rows, width, x, y, PERIOD_LINE)

    # 底轴
    base = height - pad_b
    for x in range(width):
        _px(rows, width, x, base, BASELINE)

    def sample(idx):
        """idx=1 取主队，2 取客队，按时间线性插值到每一列。"""
        ts = [p[0] for p in series]
        pts = []
        for x in range(width):
            t = x / (width - 1) * total
            i = bisect.bisect_right(ts, t) - 1
            if i < 0:
                pts.append(series[0][idx])
                continue
            if i >= len(series) - 1:
                pts.append(series[-1][idx])
                continue
            t0, t1 = ts[i], ts[i + 1]
            v0, v1 = series[i][idx], series[i + 1][idx]
            pts.append(v1 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0))
        return pts

    # 客队先画、主队后画，交叉处主队压在上层
    home_vals, away_vals = sample(1), sample(2)

    # 领先区域淡色填充：谁在前面，两条线之间就染谁的颜色。
    # 累计得分图的两条线天然贴得很近，靠填充才看得出"什么时候谁领先"。
    # 用 _blend 而非直接替换，网格线才能透出来当分数刻度用。
    for x in range(width):
        yh, ya = y_of(home_vals[x]), y_of(away_vals[x])
        if yh == ya:
            continue
        if yh < ya:                     # 主队分高在上
            tint, lo, hi = HOME_LINE, yh + 1, ya
        else:
            tint, lo, hi = AWAY_LINE, ya + 1, yh
        for y in range(lo, hi):
            _blend(rows, width, x, y, tint, FILL_ALPHA)

    for vals, color in ((away_vals, AWAY_LINE), (home_vals, HOME_LINE)):
        prev_y = y_of(vals[0])
        for x, v in enumerate(vals):
            y = y_of(v)
            _thick(rows, width, x, prev_y, y, color, half=3)
            prev_y = y

    write_png(out_path, width, height, rows)
    return out_path
