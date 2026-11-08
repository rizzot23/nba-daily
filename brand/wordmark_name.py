# -*- coding: utf-8 -*-
"""一球不落 · 文字标志 v5（2026-11-08 定）

层级（2026-11-08 用户定版：头像不要两字简称，写全名四字）：

  账号名  一球不落（四字）
  字标    球不落（三字等大紧排，替代 v4 的「去球吧」）—— 页眉 / 封面角标 / 文末署名
  头像    一球不落（四字 2×2）—— 与账号名一致，语义完整

为什么四字只能 2×2：
  v4 brief 的硬底线是 48px 圆形里每字 ≥16px。四字横排每字约 11px 会糊成一团墨，
  2×2 每字约 16px 是可辨下限。得意黑里「一」只有一横，48px 下这一行偏轻 ——
  这是字形本身的事实，验收如实记录，不靠描边 / 加粗去伪造笔画。
  两字「不落」曾作为对照（48px 最清楚），用户最终选择「头像写全名」优先。

沿用 v4 的一切：皮棕 #D9925A / 墨 #16131B / 得意黑 SmileySans-Oblique /
640×640 不透明 RGB 四角同色。不加纹路、不加圆环、不加装饰。

定稿文件 wordmark.py / brand-final.png / out4/ 一律不动，保留为 v4 历史。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
FONT = str(ROOT / "fonts" / "SmileySans-Oblique.ttf")
LABEL = "C:/Windows/Fonts/msyh.ttc"

LEATHER = (217, 146, 90)
INK = (22, 19, 27)
WHT = (245, 244, 214)
PAPER = (250, 249, 246)

SIZE = 640
SS = 4
SZ = int(SIZE * SS * 0.46)
TRACK = -0.045
# 光学字距：「球」右是斜笔、「不」左是撇，少压；「不」下收窄、「落」草字头上宽，可多压
GAPS_QBL = (-0.035, -0.065)


def word(chars, size, fill, gaps):
    """按基线对齐横排，裁到字边界的透明图"""
    fonts = [ImageFont.truetype(FONT, size) for _ in chars]
    asc = max(f.getmetrics()[0] for f in fonts)
    desc = max(f.getmetrics()[1] for f in fonts)
    g = [size * v for v in gaps][: max(0, len(chars) - 1)]
    widths = [f.getlength(c) for c, f in zip(chars, fonts)]
    total = sum(widths) + sum(g)
    pad = size // 4
    im = Image.new("RGBA", (int(total) + pad * 2, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = float(pad)
    for i, (c, f, w) in enumerate(zip(chars, fonts, widths)):
        d.text((x, pad + asc - f.getmetrics()[0]), c, font=f, fill=fill + (255,))
        x += w + (g[i] if i < len(g) else 0)
    return im.crop(im.getbbox())


def stacked(lines, size, track, line_gap, fill):
    rows = [word(line, size, fill, [track] * (len(line) - 1)) for line in lines]
    w = max(r.width for r in rows)
    h = sum(r.height for r in rows) + line_gap * (len(rows) - 1)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for r in rows:
        im.alpha_composite(r, ((w - r.width) // 2, y))
        y += r.height + line_gap
    return im


def avatar(txt, inset, size=SIZE, bg=LEATHER):
    """圆底 + 按内接正方形缩放的文字；四角补成不透明皮棕"""
    big = size * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([0, 0, big - 1, big - 1], fill=bg + (255,))
    inner = big * (1 - inset * 2)
    r = min(inner / txt.width, inner / txt.height)
    t = txt.resize((max(1, int(txt.width * r)), max(1, int(txt.height * r))), Image.LANCZOS)
    im.alpha_composite(t, ((big - t.width) // 2, (big - t.height) // 2))
    sq = im.resize((size, size), Image.LANCZOS)
    flat = Image.new("RGBA", (size, size), bg + (255,))
    flat.alpha_composite(sq)
    return flat.convert("RGB")


def circle(img, s):
    m = Image.new("L", (s * 4, s * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, s * 4 - 1, s * 4 - 1], fill=255)
    m = m.resize((s, s), Image.LANCZOS)
    out = img.resize((s, s), Image.LANCZOS).convert("RGBA")
    out.putalpha(m)
    return out


def make_mark():
    return word("球不落", 300, INK, GAPS_QBL)


def make_avatar():
    """定稿：全名「一球不落」2×2，覆盖上传版"""
    return avatar(stacked(["一球", "不落"], SZ, TRACK, int(SZ * 0.10), INK), 0.17)


def make_avatar_short():
    """对照：上一版两字「不落」，48px 更清楚但已被用户弃用"""
    return avatar(word("不落", SZ, INK, [TRACK]), 0.19)


def brand_sheet(mark, av, prev):
    W, H = 1080, 470
    sheet = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(sheet)
    title = ImageFont.truetype(LABEL, 20)
    lab = ImageFont.truetype(LABEL, 15)
    small = ImageFont.truetype(LABEL, 12)
    d.text((36, 22), "一球不落 · 视觉体系", font=title, fill=(30, 28, 32))
    d.text((36, 54),
           "账号名 一球不落  →  字标 球不落  →  头像 一球不落 2×2（2026-11-08 定版，头像写全名）",
           font=small, fill=(110, 106, 102))

    cards = [(36, 320), (372, 320), (708, 336)]
    for x, w in cards:
        d.rounded_rectangle([x, 88, x + w, 424], radius=12, fill=(255, 255, 255),
                            outline=(229, 224, 216), width=1)

    # 字标
    d.text((56, 106), "字标 · 球不落", font=lab, fill=(30, 28, 32))
    m = mark.resize((int(mark.width * 74 / mark.height), 74), Image.LANCZOS)
    sheet.paste(m, (36 + (320 - m.width) // 2, 176), m)
    d.text((56, 286), "三字等大紧排 · 墨色 · 透明底", font=small, fill=(110, 106, 102))
    d.text((56, 310), "用于页眉 / 封面角标 / 文末署名", font=small, fill=(110, 106, 102))
    d.text((56, 340), "替代 v4 的「去球吧」", font=small, fill=(110, 106, 102))

    for x, w, img, head, note in (
        (372, 320, av, "头像 · 一球不落（定稿）", "四字 2×2，上传这一张"),
        (708, 336, prev, "对照 · 不落 两字", "上一版，已弃用"),
    ):
        d.text((x + 20, 104), head, font=lab, fill=(30, 28, 32))
        d.text((x + 20, 130), note, font=small, fill=(110, 106, 102))
        bx = x + (w - 170) // 2
        sheet.paste(img.resize((170, 170), Image.LANCZOS), (bx, 152))
        c48 = circle(img, 48)
        sheet.paste(c48, (bx + 6, 350), c48)
        c96 = c48.resize((96, 96), Image.NEAREST)
        sheet.paste(c96, (bx + 66, 326), c96)
    return sheet


def main():
    m = make_mark()
    m.save(ROOT / "wordmark-qiubuluo.png", "PNG", optimize=True)
    word("球不落", 300, WHT, GAPS_QBL).save(ROOT / "wordmark-qiubuluo-reverse.png", "PNG", optimize=True)

    av = make_avatar()
    av.save(ROOT / "avatar-square.png", "PNG", optimize=True)      # 覆盖上传版
    brand_sheet(m, av, make_avatar_short()).save(ROOT / "brand-sheet.png", "PNG", optimize=True)

    for fn in ("wordmark-qiubuluo.png", "wordmark-qiubuluo-reverse.png",
               "avatar-square.png", "brand-sheet.png"):
        p = ROOT / fn
        im = Image.open(p)
        print(f"{fn:36s} {p.stat().st_size // 1024:>3} KB  {im.size} {im.mode}")
    print("头像四角:", [av.getpixel(q) for q in ((0, 0), (639, 0), (0, 639), (639, 639))])


if __name__ == "__main__":
    main()
