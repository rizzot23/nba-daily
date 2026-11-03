# -*- coding: utf-8 -*-
"""去球吧 标志 · 第二参考图（黄蓝双色地 + 球压分界线）

比例全部来自 brand/reference2.png 实测（原图 639×737）：
  球心   (0.509W, 0.513H)      球径 0.40W
  分界线 过 (1.014W, 0)，斜率 dx/dy = −0.826（与水平夹角 50.4°），线宽 0.103W
  球心到线心垂距 0.062W —— 线是穿过球的，不是相切

色值取样自原图：
  左下 #EECD14 黄   右上 #708584 蓝灰   线 #F7F5E6 暖白   球 #16131B 墨

两处修正（都不是随手改的，理由写在 brand/README-v2.md）：
  1. 球径 20 → 17。实测 40% 是相对方形照片，在圆形头像里同样的比例视觉过重，
     会把分界线吃掉大半，只剩两小段。17 保留「压线」关系，同时留出线。
  2. 线穿过球时在球内收窄成 2.8（球外 10.3）。这一条同时解决三件事：
     线不断、球是完整的圆、那条窄缝正好是篮球的球缝。

单色版之所以能成立，全靠第 2 条：白球压在墨线上，缝和线连成一体，线仍是连续的。

画布 100 单位，外圆 r=50。
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "out2"
OUT.mkdir(exist_ok=True)

YEL = (238, 205, 20)
SLA = (112, 133, 132)
WHT = (247, 245, 230)
INK = (22, 19, 27)
GRAY = (138, 138, 138)

FONT = str(ROOT / "fonts" / "SmileySans-Oblique.ttf")
MSYH = "C:/Windows/Fonts/msyh.ttc"

CX, CY = 50.9, 51.3
BALL_R = 17.0
P0X, K = 101.4, -0.826
LINE_W = 10.3
SEAM_W = 2.8
NX, NY = 0.771, 0.637

S = 640
U = S / 100.0


def _pt(y, off=0.0):
    return ((P0X + K * y + NX * off) * U, (y + NY * off) * U)


def _band(off_lo, off_hi, y0=-40, y1=140):
    return [_pt(y0, off_lo), _pt(y1, off_lo), _pt(y1, off_hi), _pt(y0, off_hi)]


def _right_half(off):
    return [_pt(-40, off), _pt(140, off), _pt(140, off + 200), _pt(-40, off + 200)]


def build(left=YEL, right=SLA, ball=INK, line=WHT, seam=WHT,
          ball_r=BALL_R, line_w=LINE_W, seam_w=SEAM_W):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    d.ellipse([0, 0, S - 1, S - 1], fill=left + (255,))

    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(lay).polygon(_right_half(line_w / 2), fill=right + (255,))
    im = Image.alpha_composite(im, Image.composite(
        lay, Image.new("RGBA", (S, S), (0, 0, 0, 0)), im.split()[3]))

    ln = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ln).polygon(_band(-line_w / 2, line_w / 2), fill=line + (255,))
    im = Image.alpha_composite(im, ln)

    cx, cy, rr = CX * U, CY * U, ball_r * U
    bl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bl)
    bd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=ball + (255,))
    bd.polygon(_band(-seam_w / 2, seam_w / 2), fill=seam + (255,))
    bm = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bm).ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    bl.putalpha(Image.composite(bl.split()[3], Image.new("L", (S, S), 0), bm))
    im = Image.alpha_composite(im, bl)
    return im


def circle(im):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse([0, 0, S - 1, S - 1], fill=255)
    out = im.copy()
    out.putalpha(Image.composite(im.split()[3], Image.new("L", (S, S), 0), m))
    return out


def avatar(size=640):
    return circle(build()).resize((size, size), Image.LANCZOS)


def mono(size=640):
    return circle(build(left=INK, right=GRAY, ball=WHT, line=INK, seam=INK)
                  ).resize((size, size), Image.LANCZOS)


def reverse(size=640):
    return circle(build(left=WHT, right=GRAY, ball=INK, line=WHT, seam=WHT)
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
        avatar(s).save(OUT / f"v2-avatar-{s}.png")
    for s in (512, 256, 128, 64, 32):
        avatar(s).save(OUT / f"v2-mark-{s}.png")
    for s in (512, 256, 128, 64, 32):
        mono(s).save(OUT / f"v2-mono-{s}.png")
    for s in (512, 128, 32):
        reverse(s).save(OUT / f"v2-reverse-{s}.png")
    scale_test().save(OUT / "v2-scale-test.png")
    mock_list().save(OUT / "v2-mock-list.png")
    lockup().save(OUT / "v2-lockup.png")
    lockup(dark=True).save(OUT / "v2-lockup-reverse.png")
    print("已生成", len(list(OUT.glob("v2-*"))), "个文件")


if __name__ == "__main__":
    main()
