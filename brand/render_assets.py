# -*- coding: utf-8 -*-
"""去球吧 · 标志资产渲染

坐标全部来自 brand/mark.json，保证头像版和标记版是同一套骨架：
    环    (33, 28.5)  rx18  ry11.7  线宽 4.2      ← 参考图实测 1.54:1
    球    (64, 64)    r17                          ← 参考图实测 0.36W
    地线  y81  x12→88  线宽 3.2                    ← 与球底相切
头像版只把「实心球面」换成「球」字，其余不动。

用法：python brand/render_assets.py
产物：brand/out/
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
FONT_ZH = ROOT / "fonts" / "SmileySans-Oblique.ttf"
SS = 4  # 超采样倍数

CFG = json.loads((ROOT / "mark.json").read_text(encoding="utf-8"))
PAL = CFG["palette"]
WOOD = PAL["primary"]
INK = PAL["structural"]
IVORY = PAL["panel"]

RING = dict(cx=33, cy=28.5, rx=18, ry=11.7, w=3.6)
BALL = dict(cx=64, cy=64, r=17)
LINE = dict(x1=12, x2=88, y=81, w=3.2)
CHAR = dict(text="球", cx=64, cap=40, bottom=79.2)


def _font(cap, unit):
    """cap = 字的墨迹高度（0-100 单位），换算成像素字号。"""
    probe = ImageFont.truetype(str(FONT_ZH), 200)
    bb = probe.getbbox(CHAR["text"])
    ratio = 200 / (bb[3] - bb[1])          # 字号 / 墨迹高度
    return ImageFont.truetype(str(FONT_ZH), max(6, int(round(cap * unit * ratio))))


def _text_at_bottom(d, unit, col):
    f = _font(CHAR["cap"], unit)
    bb = d.textbbox((0, 0), CHAR["text"], font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    x = CHAR["cx"] * unit - w / 2 - bb[0]
    y = CHAR["bottom"] * unit - h - bb[1]
    d.text((x, y), CHAR["text"], font=f, fill=col)


def draw_mark(size, fg, ball_col, *, field=None, char=False, ball_scale=1.0):
    """在 size×size 上画标志。field 为 None 时透明底。"""
    s = size * SS
    u = s / 100.0
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    if field:
        d.ellipse([0, 0, s - 1, s - 1], fill=field)

    r = RING
    d.ellipse([(r["cx"] - r["rx"]) * u, (r["cy"] - r["ry"]) * u,
               (r["cx"] + r["rx"]) * u, (r["cy"] + r["ry"]) * u],
              outline=fg, width=max(1, int(round(r["w"] * u))))

    if char:
        _text_at_bottom(d, u, fg)
    else:
        b = BALL
        rr = b["r"] * ball_scale
        d.ellipse([(b["cx"] - rr) * u, (b["cy"] - rr) * u,
                   (b["cx"] + rr) * u, (b["cy"] + rr) * u], fill=ball_col)

    ln = LINE
    d.rectangle([ln["x1"] * u, (ln["y"] - ln["w"] / 2) * u,
                 ln["x2"] * u, (ln["y"] + ln["w"] / 2) * u], fill=fg)

    return im.resize((size, size), Image.LANCZOS)


def save(im, name):
    im.save(OUT / name)
    return OUT / name


# ---------------------------------------------------------------- 头像
def build_avatars():
    """墨黑底 + 木色元素（推荐）：白色信息流里最跳。"""
    for size in (640, 320, 160, 96, 64, 48, 32):
        im = draw_mark(size, WOOD, WOOD, field=INK, char=True)
        save(im, f"avatar-{size}.png")
    # 木色底 + 墨黑元素（备选）
    for size in (640, 160, 96, 64, 48, 32):
        im = draw_mark(size, INK, INK, field=WOOD, char=True)
        save(im, f"avatar-wood-{size}.png")


# ---------------------------------------------------------------- 标记
def build_marks():
    for size in (512, 128, 32, 16):
        save(draw_mark(size, INK, WOOD), f"mark-{size}.png")
    # 反白版：深底上用
    for size in (512, 128):
        save(draw_mark(size, IVORY, WOOD), f"mark-reverse-{size}.png")
    # 单色版：烫金 / 单色印刷
    for size in (512, 128):
        save(draw_mark(size, INK, INK), f"mark-mono-{size}.png")


# ---------------------------------------------------------------- 横排锁定
def build_lockup(scale=2):
    """标记 + 去球吧 + 副行。用于战报页眉、结尾署名。"""
    h = 120 * scale
    mark_h = 104 * scale
    pad = 14 * scale
    f_main = ImageFont.truetype(str(FONT_ZH), int(60 * scale))
    f_sub = ImageFont.truetype(str(FONT_ZH), int(21 * scale))

    probe = Image.new("RGBA", (10, 10))
    pd = ImageDraw.Draw(probe)
    b1 = pd.textbbox((0, 0), "去球吧", font=f_main)
    b2 = pd.textbbox((0, 0), "NBA 每日战报", font=f_sub)
    w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
    w2, h2 = b2[2] - b2[0], b2[3] - b2[1]

    gap = 18 * scale
    W = pad * 2 + mark_h + gap + max(w1, w2) + 6 * scale
    im = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    mark = draw_mark(mark_h, INK, WOOD)
    im.alpha_composite(mark, (pad, (h - mark_h) // 2))

    tx = pad + mark_h + gap
    block = h1 + 4 * scale + h2
    ty = (h - block) // 2
    d.text((tx - b1[0], ty - b1[1]), "去球吧", font=f_main, fill=INK)
    d.text((tx - b2[0], ty + h1 + 4 * scale - b2[1]), "NBA 每日战报",
           font=f_sub, fill=(110, 97, 87, 255))

    save(im, "lockup.png")
    # 反白版
    im2 = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(im2)
    m2 = draw_mark(mark_h, IVORY, WOOD)
    im2.alpha_composite(m2, (pad, (h - mark_h) // 2))
    d2.text((tx - b1[0], ty - b1[1]), "去球吧", font=f_main, fill=IVORY)
    d2.text((tx - b2[0], ty + h1 + 4 * scale - b2[1]), "NBA 每日战报",
            font=f_sub, fill=(206, 154, 110, 255))
    save(im2, "lockup-reverse.png")


# ---------------------------------------------------------------- 场景模拟
def build_mock():
    """在真实尺寸下看一眼：消息列表里的样子。"""
    W, H = 780, 420
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 17)
    fm = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    rows = [("avatar-48.png", "今天 15 场，最狠的一刻在最后 7.3 秒", (255, 255, 255), "深底"),
            ("avatar-wood-48.png", "昨天 4 场，两场打到最后一分钟", (247, 247, 247), "木底")]
    y = 20
    for name, msg, bg, _ in rows:
        d.rectangle([0, y, W, y + 76], fill=bg)
        a = Image.open(OUT / name).convert("RGBA").resize((52, 52), Image.LANCZOS)
        im.paste(a, (24, y + 12), a)
        d.text((92, y + 14), "去球吧", font=f, fill=(20, 20, 20))
        d.text((92, y + 42), msg, font=fm, fill=(150, 150, 150))
        y += 76

    d.text((30, 196), "两版并排（96 / 64 / 48 / 32px）", font=fm, fill=(120, 120, 120))
    for r, (name, label) in enumerate([("avatar", "深底"), ("avatar-wood", "木底")]):
        d.text((30, 226 + r * 92), label, font=fm, fill=(120, 120, 120))
        x = 72
        for sz in (96, 64, 48, 32):
            fn = OUT / (f"{name}-{sz}.png" if (OUT / f"{name}-{sz}.png").exists()
                        else f"{name}-640.png")
            a = Image.open(fn).convert("RGBA").resize((sz, sz), Image.LANCZOS)
            im.paste(a, (x, 216 + r * 92), a)
            d.text((x, 216 + r * 92 + sz + 2), f"{sz}", font=fm, fill=(170, 170, 170))
            x += sz + 34
    save(im, "mock-list.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_marks()
    build_avatars()
    build_lockup()
    build_mock()
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:26s} {p.stat().st_size/1024:6.1f} KB")
