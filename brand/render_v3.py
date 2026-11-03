# -*- coding: utf-8 -*-
"""去球吧 标志 · 第三版：照片简笔画

和第二版（v2）的根本区别
  v2 是几何抽象——照片被压成两片色块 + 一条线 + 一个实心圆，球上没有球缝，
  靠"线在球内收窄"假扮球缝，结果在信息流里不像篮球。
  v3 是把照片画成简笔插画——照片里有的每一样东西都保留：
  两片地色、那条白线、一颗有球缝的橙球，只是把质感换成平涂。

比例来自 brand/reference2.png（639×737）实测，映射方式
  取照片中心正方形（y 49..688）铺满圆直径 100 单位，所以 1 单位 = 6.39 px

  球心  (309,391) → (48.4,53.5)    球半径 146 → 21.5
  白线  x = 653.5 − 0.7766 y       线宽（法向）55 → 8.5
  球   4 条缝，端点一律伸出球缘外再裁掉，收口才干净

色值取样
  黄 #EECD13  蓝灰 #718785  暖白 #F5F4D6  球 #CE7E49  缝 #24150D

球缝结构说明（这里踩过坑，写下来免得下次再犯）
  照片是斜俯视：赤道被透视压成浅弧、交叉点跑到球心上方 0.46R、
  左右两条经线贴着球缘只剩 0.08R。逐点照抄的结果是上半球挤成一团、
  左右线变成第二圈轮廓，看起来像地球仪。
  所以按"简体画"的方式提炼：保留四条缝的相对方位与倾斜，
  但把它们放到能读出来的位置——横缝留到球心上方 0.28R（照片 0.46R 太挤，
  0.10R 又退回侧面平视，0.28R 是这两头之间能读出俯视感的位置），左右弧离缘 0.22R。
  球缝端点在球缘处彼此分开、各自收口，不汇聚成乱线（这一点是像不像篮球的关键）。
  整组倾斜 +6°（画布 y 向下，顺照片"横缝左高右低"的方向）；写成负角会反过来。
"""
from pathlib import Path
from math import hypot, cos, sin, pi, radians
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "out3"
OUT.mkdir(exist_ok=True)

YEL = (238, 205, 19)
SLA = (113, 135, 133)
WHT = (245, 244, 214)
INK = (22, 19, 27)
BALL = (212, 132, 76)
SEAM = (36, 21, 13)
GRAY = (138, 138, 138)

FONT = str(ROOT / "fonts" / "SmileySans-Oblique.ttf")
MSYH = "C:/Windows/Fonts/msyh.ttc"

CX, CY = 48.4, 53.5
BALL_R = 21.5
P0X, A = 96.3, -0.7766
LINE_W = 8.5
SEAM_W = 1.9
NX, NY = 0.790, 0.613

S = 640
SS = 4                      # 超采样，缩回 S 时线条自然抗锯齿
BIG = S * SS
U = BIG / 100.0

TILT = radians(6)           # 整组球缝随球的姿态倾：照片里横缝左高右低，约 5°


def _ell(cx, cy, a, b, t0, t1, n=150):
    out = []
    ct, st = cos(TILT), sin(TILT)
    for i in range(n + 1):
        t = t0 + (t1 - t0) * i / n
        x, y = a * cos(t), b * sin(t)
        out.append((cx + x * ct - y * st, cy + x * st + y * ct))
    return out


def _seams():
    mer = _ell(0.03, 0, 0.20, 1.10, -pi / 2, pi / 2)          # 经线：穿过球心，微右凸
    eq = _ell(0, -0.28, 1.06, -0.14, pi, 2 * pi)              # 纬线：球心上方 0.28R，中央下凹（俯视的近边）
    left = _ell(-0.42, 0, 0.36, 1.04, pi / 2, 1.5 * pi)       # 左经线，凸向左，离缘 0.22R
    right = _ell(0.42, 0, 0.36, 1.04, -pi / 2, pi / 2)        # 右经线，凸向右
    return [mer, eq, left, right]


SEAMS = _seams()


def _taper(pts, w0, wm, w1):
    """把折线转成带宽度的多边形；宽度沿路径在 w0→wm→w1 之间线性过渡"""
    n = len(pts)
    L, R = [], []
    for i, p in enumerate(pts):
        if i == 0:
            dx, dy = pts[1][0] - p[0], pts[1][1] - p[1]
        elif i == n - 1:
            dx, dy = p[0] - pts[-2][0], p[1] - pts[-2][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        d = hypot(dx, dy) or 1
        nx, ny = -dy / d, dx / d
        t = i / (n - 1)
        w = (w0 + (wm - w0) * t * 2) if t < 0.5 else (wm + (w1 - wm) * (t - 0.5) * 2)
        w /= 2
        L.append((p[0] + nx * w, p[1] + ny * w))
        R.append((p[0] - nx * w, p[1] - ny * w))
    return L + R[::-1]


def _pt(y, off=0.0):
    return ((P0X + A * y + NX * off) * U, (y + NY * off) * U)


def _band(lo, hi, y0=-45, y1=145):
    return [_pt(y0, lo), _pt(y1, lo), _pt(y1, hi), _pt(y0, hi)]


def _side(off, depth):
    return [_pt(-45, off), _pt(145, off), _pt(145, off + depth), _pt(-45, off + depth)]


def build(left=YEL, right=SLA, ball=BALL, seam=SEAM, line=WHT,
          ball_r=BALL_R, line_w=LINE_W, seam_w=SEAM_W, edge=None):
    im = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 1. 黄底
    d.ellipse([0, 0, BIG - 1, BIG - 1], fill=left + (255,))
    # 2. 右上蓝灰
    d.polygon(_side(line_w / 2, 220), fill=right + (255,))
    # 3. 白线
    d.polygon(_band(-line_w / 2, line_w / 2), fill=line + (255,))

    # 4. 球 + 球缝（球压在白线上，照片里线就是被球挡断的）
    cx, cy, rr = CX * U, CY * U, ball_r * U
    bl = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bl)
    if edge:
        # 同色版里球和线同色，必须描一圈反色才分得开
        er = rr + seam_w * 1.5 * U
        bd.ellipse([cx - er, cy - er, cx + er, cy + er], fill=edge + (255,))
    bd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=ball + (255,))
    w = seam_w * U
    for pts in SEAMS:
        path = [(cx + p[0] * rr, cy + p[1] * rr) for p in pts]
        bd.polygon(_taper(path, w, w, w), fill=seam + (255,))
        r0 = w / 2
        for p in (path[0], path[-1]):
            bd.ellipse([p[0] - r0, p[1] - r0, p[0] + r0, p[1] + r0], fill=seam + (255,))

    bm = Image.new("L", (BIG, BIG), 0)
    mr = rr + (seam_w * 1.5 * U if edge else 0)
    ImageDraw.Draw(bm).ellipse([cx - mr, cy - mr, cx + mr, cy + mr], fill=255)
    bl.putalpha(Image.composite(bl.split()[3], Image.new("L", (BIG, BIG), 0), bm))
    im = Image.alpha_composite(im, bl)

    # 5. 外圆裁切
    m = Image.new("L", (BIG, BIG), 0)
    ImageDraw.Draw(m).ellipse([0, 0, BIG - 1, BIG - 1], fill=255)
    im.putalpha(Image.composite(im.split()[3], Image.new("L", (BIG, BIG), 0), m))
    return im.resize((S, S), Image.LANCZOS)


def avatar(size=640):
    return build().resize((size, size), Image.LANCZOS)


def mono(size=640):
    """单色：墨 / 中灰 / 纸白三档。球与线同色，靠一圈墨边隔开"""
    return build(left=INK, right=GRAY, ball=WHT, seam=INK, line=WHT, edge=INK,
                 ).resize((size, size), Image.LANCZOS)


def reverse(size=640):
    """深底反白"""
    return build(left=WHT, right=GRAY, ball=INK, seam=WHT, line=INK, edge=WHT,
                 ).resize((size, size), Image.LANCZOS)


def flat(size=640):
    """两色平版，给单色印刷或极简场景"""
    return build(left=INK, right=INK, ball=WHT, seam=INK, line=WHT, edge=INK,
                 ).resize((size, size), Image.LANCZOS)


def lockup(dark=False, scale=2):
    w, h = 960 * scale, 300 * scale
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mh = int(184 * scale)
    mk = avatar(mh)
    im.alpha_composite(mk, (0, (h - mh) // 2))
    f1 = ImageFont.truetype(FONT, int(64 * scale))
    f2 = ImageFont.truetype(FONT, int(27 * scale))
    col = WHT if dark else INK
    dd = ImageDraw.Draw(im)
    tx = mh + int(40 * scale)
    b1 = dd.textbbox((0, 0), "去球吧", font=f1)
    b2 = dd.textbbox((0, 0), "NBA 每日战报", font=f2)
    gap = int(26 * scale)
    total = (b1[3] - b1[1]) + gap + (b2[3] - b2[1])
    y1 = (h - total) // 2 - b1[1]
    y2 = y1 + (b1[3] - b1[1]) + gap - b2[1]
    dd.text((tx, y1), "去球吧", font=f1, fill=col + (255,))
    dd.text((tx, y2), "NBA 每日战报", font=f2, fill=col + (255,))
    return im.crop(im.getbbox())


def scale_test():
    f = ImageFont.truetype(MSYH, 12)
    tiles = [(s, mono(s)) for s in (64, 48, 32, 24, 16)]
    W = sum(t.width for _, t in tiles) + 44 * len(tiles) + 40
    sheet = Image.new("RGB", (W, 150), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    x = 30
    for s, t in tiles:
        sheet.paste(t, (x, 34), t)
        d.text((x, 34 + s + 8), f"{s}px", font=f, fill=(150, 150, 150))
        x += s + 44
    return sheet


def mock_list():
    W, H = 860, 430
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(MSYH, 17)
    fm = ImageFont.truetype(MSYH, 13)
    a52 = avatar(52)
    rows = [("今天 15 场，最狠的一刻在最后 7.3 秒", (255, 255, 255)),
            ("昨天 4 场，两场打到最后一分钟", (247, 247, 247))]
    y = 16
    for msg, bg in rows:
        d.rectangle([0, y, W, y + 76], fill=bg)
        im.paste(a52, (24, y + 12), a52)
        d.text((92, y + 14), "去球吧", font=f, fill=(20, 20, 20))
        d.text((92, y + 42), msg, font=fm, fill=(150, 150, 150))
        y += 76
    d.text((30, 196), "48px 在列表里的实际观感 ／ 各尺寸对照", font=fm, fill=(130, 130, 130))
    x = 30
    for sz in (128, 96, 64, 48, 32):
        t = avatar(sz)
        im.paste(t, (x, 228), t)
        d.text((x, 230 + sz + 2), str(sz), font=fm, fill=(170, 170, 170))
        x += sz + 32
    return im


def main():
    for s in (640, 320, 256, 160, 128, 96, 64, 48, 32):
        avatar(s).save(OUT / f"v3-avatar-{s}.png")
    for s in (512, 256, 128, 64, 32):
        avatar(s).save(OUT / f"v3-mark-{s}.png")
        mono(s).save(OUT / f"v3-mono-{s}.png")
    for s in (512, 128, 32):
        reverse(s).save(OUT / f"v3-reverse-{s}.png")
        flat(s).save(OUT / f"v3-flat-{s}.png")
    scale_test().save(OUT / "v3-scale-test.png")
    mock_list().save(OUT / "v3-mock-list.png")
    lockup().save(OUT / "v3-lockup.png")
    lockup(dark=True).save(OUT / "v3-lockup-reverse.png")
    print("已生成", len(list(OUT.glob("v3-*"))), "个文件")


if __name__ == "__main__":
    main()
