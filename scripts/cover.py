#!/usr/bin/env python3
"""生成公众号头条封面图（900×383，2.35:1）。

为什么自己画而不是找图：NBA 比赛照片和动图都是版权素材，公众号用比赛图被投诉
下架的案例很多，而单色配色和排版本身不受版权保护。所以封面只用两队的官方主色
（ESPN 的 team.color）+ 比分 + 日期，零风险，还能顺便做成固定版式。

底色用浅色（白 → 极浅灰）而不是深色：公众号信息流是白底，深色封面像块补丁，
浅色反而更像正经媒体出的图。辨认靠两侧的球队色条 + 淡色光球。

依赖 Pillow 和一个中文 TTF。字体**不能**用 Windows 的微软雅黑（微软版权，不能进仓库，
CI 上也没有），Actions 里 apt 装 fonts-wqy-zenhei（文泉驿正黑，可商用）。

用法：
    python scripts/cover.py            # 读 docs/latest.json，写 docs/cover.png

没有 Pillow 或找不到中文字体时只打印警告并退出 0，不影响出稿。
"""

import colorsys
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LATEST = BASE_DIR.parent / "docs" / "latest.json"
OUT = BASE_DIR.parent / "docs" / "cover.png"

W, H = 900, 383

# 依次尝试。CI 上第一个命中（apt 装完就在），本地 Windows 会落到微软雅黑。
FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0),
    ("C:/Windows/Fonts/msyhbd.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]

ACCENT = (194, 65, 12)        # 和正文同一个橙 #c2410c
INK = (22, 22, 28)            # 比分、队名的深墨
SUB = (58, 58, 66)            # 队名用，比 INK 轻一点
DIM = (138, 138, 146)         # 日期、脚注
COLON = (188, 188, 198)
BG_TOP = (255, 255, 255)
BG_BOTTOM = (238, 240, 244)


def hex_rgb(s, fallback=(70, 70, 78)):
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return fallback
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def bar_color(rgb):
    """球队色条用色。原色直接铺在白底上有两个问题：黄色系（勇士/湖人/爵士）
    几乎看不见，深蓝色系（鹈鹕/凯尔特人）又像一道黑边。所以把亮度夹到
    0.26～0.46 这个区间，色相饱和度保留，深浅队都能看出是彩色。

    近灰色的队色（马刺银、纯黑）要单独放过：对它们加饱和度会把银灰染成蓝、
    把纯黑染成暗红，因为灰度色的色相分量本来是没有意义的。"""
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    gray = s < 0.22
    if l > 0.46:
        l = 0.44
        s = min(s, 0.06) if gray else min(1.0, s + 0.15)
    elif l < 0.26:
        l = 0.30
        s = min(s, 0.06) if gray else min(1.0, s + 0.12)
    elif gray:
        s = min(s, 0.06)
    return tuple(int(max(0, min(255, v * 255))) for v in colorsys.hls_to_rgb(h, l, s))


def _shift_light(rgb, delta):
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    l = max(0.12, min(0.62, l + delta))
    return tuple(int(max(0, min(255, v * 255))) for v in colorsys.hls_to_rgb(h, l, s))


def bar_pair(away_rgb, home_rgb):
    """两队色条。同色系的对阵（鹈鹕深蓝 vs 灰熊中蓝、湖人对快船）直接铺色
    会变成一整条，看不出左右是谁，所以色相太近时把客队压暗、主队提亮。"""
    ca, cb = bar_color(away_rgb), bar_color(home_rgb)
    ha = colorsys.rgb_to_hls(*[v / 255 for v in ca])[0]
    hb = colorsys.rgb_to_hls(*[v / 255 for v in cb])[0]
    d = abs(ha - hb)
    d = min(d, 1 - d)
    if d < 0.09:                      # 色相差不到约 32°
        ca = _shift_light(ca, -0.11)
        cb = _shift_light(cb, +0.14)
    return ca, cb


def pick_font(size):
    from PIL import ImageFont

    for path, idx in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=idx)
            except Exception:
                continue
    return None


def build():
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        print("没装 Pillow，跳过封面。CI 里需要 pip install pillow")
        return 0

    if not LATEST.exists():
        print("没有 latest.json，跳过封面")
        return 0

    d = json.loads(LATEST.read_text(encoding="utf-8"))
    cv = d.get("cover") or {}
    if not cv:
        print("latest.json 里没有 cover 字段（当天可能没有比赛），跳过封面")
        return 0

    big = pick_font(132)
    name_font = pick_font(36)
    small = pick_font(21)
    if big is None or name_font is None:
        print("找不到中文字体，跳过封面。CI 里需要 apt-get install fonts-wqy-zenhei")
        return 0

    m = 60

    # 浅色竖向渐变底
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        draw.line(
            [(0, y), (W, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )

    # 左上 / 右下各一团队色柔光，很淡，只负责透气，不抢字
    aw = hex_rgb(cv.get("away_color"))
    hm = hex_rgb(cv.get("home_color"))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-230, -200, 430, 330], fill=aw + (52,))
    gd.ellipse([W - 430, H - 330, W + 230, H + 200], fill=hm + (52,))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    # 顶部一条两队拼色横带：左半客队、右半主队，中间一道白缝
    draw = ImageDraw.Draw(img)
    bh = 12
    ca, cb = bar_pair(aw, hm)
    draw.rectangle([0, 0, W // 2 - 2, bh], fill=ca)
    draw.rectangle([W // 2 + 2, 0, W, bh], fill=cb)

    def ink_box(text, font):
        """字形实际着墨范围。PIL 的 text() 以 ascender 顶部为 y，
        数字下面会留一大截空白，直接按字号算间距必然叠字，得用 bbox 量。"""
        return draw.textbbox((0, 0), text, font=font)

    # 左上角橙底白字标签是品牌位，后面跟一行灰色小字说明品类 ——
    # 只写「去球吧」，划过信息流的人看不出这是篮球号；只写「NBA 每日战报」，
    # 又白浪费一块最显眼的位置。两个都要，但主次要分明，所以品牌用橙底实心。
    top_y = 44
    label = "去球吧"
    lw = draw.textlength(label, small)
    lb = ink_box(label, small)
    pad_x = 13
    box_r = m + lw + pad_x * 2
    draw.rounded_rectangle(
        [m - 1, top_y - 5, box_r, top_y + lb[3] + 6],
        radius=4, fill=ACCENT,
    )
    draw.text((m + pad_x, top_y), label, font=small, fill=(255, 255, 255))

    kind = "NBA 每日战报"
    date_txt = cv.get("date") or ""
    kw = draw.textlength(kind, small)
    dw = draw.textlength(date_txt, small) if date_txt else 0
    # 宽度不够就整段不画，宁可只留品牌，也不让字和日期叠在一起
    if box_r + 12 + kw < W - m - dw - 18:
        draw.text((box_r + 12, top_y), kind, font=small, fill=DIM)
    if date_txt:
        draw.text((W - m - dw, top_y), date_txt, font=small, fill=DIM)

    # 大比分向中间收拢。左右贴边会让中间空出三百多像素，像两行分开的账单；
    # 收拢之后整块像一块比分牌，两边留白对称，缩成信息流小图时也更聚。
    asc = str(cv.get("away_score", ""))
    hsc = str(cv.get("home_score", ""))
    score_top = 88
    ab = ink_box(asc, big)
    aw_w = draw.textlength(asc, big)
    hw = draw.textlength(hsc, big)
    gap = 78                       # 数字右/左边界到中线的距离
    draw.text((W / 2 - gap - aw_w, score_top), asc, font=big, fill=INK)
    draw.text((W / 2 + gap, score_top), hsc, font=big, fill=INK)

    colon = ":"
    # 别用 cb 这个名字：上面 bar_pair 的 cb 是主队色条的颜色，
    # 这里一旦覆盖成 bbox 元组，底部色带的 fill 就变成坐标数字了
    # （11-04 的封面右下角因此渲染成一块墨绿色，跟快船毫无关系）
    cbox = ink_box(colon, big)
    cw = draw.textlength(colon, big)
    # 冒号在两块数字的着墨中线上居中，不是按 ascender 中线
    mid = (ab[1] + ab[3]) / 2
    draw.text(((W - cw) / 2, score_top + mid - (cbox[1] + cbox[3]) / 2),
              colon, font=big, fill=COLON)

    # 队名贴在自家比分下沿，同一条竖线上对齐
    ny = score_top + ab[3] + 24
    anm = cv.get("away") or ""
    draw.text((W / 2 - gap - draw.textlength(anm, name_font), ny),
              anm, font=name_font, fill=SUB)
    draw.text((W / 2 + gap, ny), cv.get("home") or "", font=name_font, fill=SUB)

    # 底部一条同样的拼色带，上下封口，中间那块白就不显得空
    draw.rectangle([0, H - bh, W // 2 - 2, H], fill=ca)
    draw.rectangle([W // 2 + 2, H - bh, W, H], fill=cb)

    # 页脚：场次 · 标签（没有标签就只留场次），居中收在底部色带上方
    foot = " · ".join(x for x in (cv.get("footer") or "").split("|") if x.strip())
    if foot:
        fy = H - bh - 20 - ink_box("测", small)[3]
        draw.text(((W - draw.textlength(foot, small)) / 2, fy),
                  foot, font=small, fill=DIM)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"封面已生成：{OUT}（{OUT.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(build())
