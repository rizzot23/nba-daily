# -*- coding: utf-8 -*-
"""去球吧 · 文字标志（v4）

不画球、不画线，只用得意黑排字。两个件：

  字标  去球吧 三字等大紧排，墨色，透明底 —— 用在封面、页眉插图、文末署名
  头像  篮球皮色圆 + 「球吧」两字，墨色 —— 账号头像

为什么头像只用两个字而不是三个：
  公众号列表里头像约 48px。圆内接正方形的边长只有直径的 0.707，
  三字排进 48px 后每个字约 11px，糊成一团；两字能到 17px，32px 时仍可辨。
  「球吧」又正好是个能读的词，不算硬截。

为什么字距是 -0.053em：
  得意黑本身是斜体、字面偏宽，常规字距下三个字看起来是"三个字"而不是"一个名字"。
  压到 -16/300 之后，去与球的笔画刚好不相碰，但视觉上已经连成一体。

字体：得意黑 SmileySans-Oblique，SIL OFL 1.1，可商用。
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
OUT = ROOT / "out4"
OUT.mkdir(exist_ok=True)

FONT = str(ROOT / "fonts" / "SmileySans-Oblique.ttf")
# 头像底色：篮球皮色，偏浅一档。
# 取样自 reference2.png 的球体（206,126,73），往亮里提了约 5%，才不至于闷成巧克力棕。
# 原先用黄 (238,205,19)：信息流里更跳，但黄色和"篮球"没关系，只能当记号；
# 这个棕是它自己的颜色，代价是亮度掉了，在深色模式列表里没有黄那么扎眼。
LEATHER = (217, 146, 90)
INK = (22, 19, 27)
WHT = (245, 244, 214)
GRAY = (138, 138, 138)

TRACK = -0.053        # 字距基准，按字级的比例给，换字号不会走形
# 光学字距：等距排不等于看起来等距。「去」右侧是长斜笔，「球」左侧是竖笔，
# 两者之间要多留；「球」右侧外拓、「吧」左侧是方框，可以再压紧。
GAPS = (-0.004, -0.085)   # (去→球, 球→吧)，单位 em
AV_INSET = 0.19       # 头像里字的安全边（圆内接正方形还要再收一点）


def word(chars, size, fill, gaps=GAPS):
    """按基线对齐横排，返回裁到字边界的透明图"""
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


def avatar(size=640, bg=LEATHER, fg=INK):
    """圆底 + 「球吧」，按圆内接缩放"""
    SS = 4
    big = size * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([0, 0, big - 1, big - 1], fill=bg + (255,))

    txt = word("球吧", int(big * 0.46), fg)
    inner = big * (1 - AV_INSET * 2)
    r = min(inner / txt.width, inner / txt.height)
    txt = txt.resize((max(1, int(txt.width * r)), max(1, int(txt.height * r))), Image.LANCZOS)
    im.alpha_composite(txt, ((big - txt.width) // 2, (big - txt.height) // 2))
    return im.resize((size, size), Image.LANCZOS)


def mark(dark=False):
    """字标：三字紧排。dark=True 出反白版"""
    return word("去球吧", 300, WHT if dark else INK)


def scale_test():
    """小尺寸验证：头像 32px 起"""
    f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
    tiles = [(s, avatar(s)) for s in (96, 64, 48, 32, 24)]
    W = sum(t.width for _, t in tiles) + 36 * len(tiles) + 30
    sheet = Image.new("RGB", (W, 130), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    x = 24
    for s, t in tiles:
        sheet.paste(t, (x, 24), t)
        d.text((x, 24 + s + 8), f"{s}px", font=f, fill=(150, 150, 150))
        x += s + 36
    return sheet


def mock_list():
    """订阅号列表实景：头像 48px 那一档"""
    W, H = 860, 260
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 17)
    fm = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    a48 = avatar(48)
    rows = [("今天 15 场，最狠的一刻在最后 7.3 秒", (255, 255, 255)),
            ("昨天 4 场，两场打到最后一分钟", (247, 247, 247))]
    y = 12
    for msg, bg in rows:
        d.rectangle([0, y, W, y + 76], fill=bg)
        im.paste(a48, (24, y + 14), a48)
        d.text((92, y + 16), "去球吧", font=f, fill=(20, 20, 20))
        d.text((92, y + 44), msg, font=fm, fill=(150, 150, 150))
        y += 76
    d.text((30, 186), "48px 头像在列表里的实际观感", font=fm, fill=(130, 130, 130))
    return im


def assemble_header():
    """页眉组合：字标 + 一行小字，用来看实际用法"""
    m = mark()
    h = 90
    m2 = m.resize((int(m.width * h / m.height), h), Image.LANCZOS)
    f = ImageFont.truetype(FONT, 26)
    im = Image.new("RGBA", (m2.width + 300, h + 20), (0, 0, 0, 0))
    im.alpha_composite(m2, (0, 10))
    ImageDraw.Draw(im).text((m2.width + 18, 46), "NBA 每日战报", font=f, fill=INK + (255,))
    return im.crop(im.getbbox())


def main():
    for s in (640, 320, 160, 128, 96, 64, 48, 32):
        avatar(s).save(OUT / f"v4-avatar-{s}.png")
    avatar(640, bg=INK, fg=LEATHER).save(OUT / "v4-avatar-reverse-640.png")
    avatar(640, bg=INK, fg=WHT).save(OUT / "v4-avatar-mono-640.png")

    for h in (640, 320, 160, 80):
        m = mark()
        m = m.resize((int(m.width * h / m.height), h), Image.LANCZOS)
        m.save(OUT / f"v4-wordmark-{h}.png")
        d = mark(dark=True)
        d = d.resize((int(d.width * h / d.height), h), Image.LANCZOS)
        d.save(OUT / f"v4-wordmark-reverse-{h}.png")

    scale_test().save(OUT / "v4-scale-test.png")
    mock_list().save(OUT / "v4-mock-list.png")
    assemble_header().save(OUT / "v4-header.png")
    print("已生成", len(list(OUT.glob("v4-*"))), "个文件")


if __name__ == "__main__":
    main()
