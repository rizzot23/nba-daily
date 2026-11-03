#!/usr/bin/env python3
"""生成公众号头条封面图（900×383，2.35:1）。

为什么自己画而不是找图：NBA 比赛照片和动图都是版权素材，公众号用比赛图被投诉
下架的案例很多，而单色配色和排版本身不受版权保护。所以封面只用两队的官方主色
（ESPN 的 team.color）+ 比分 + 日期，零风险，还能顺便做成固定版式。

依赖 Pillow 和一个中文 TTF。字体**不能**用 Windows 的微软雅黑（微软版权，不能进仓库，
CI 上也没有），Actions 里 apt 装 fonts-wqy-zenhei（文泉驿正黑，可商用）。

用法：
    python scripts/cover.py            # 读 docs/latest.json，写 docs/cover.png

没有 Pillow 或找不到中文字体时只打印警告并退出 0，不影响出稿。
"""

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
INK = (245, 245, 245)
DIM = (150, 150, 155)
BG_TOP = (26, 26, 30)
BG_BOTTOM = (12, 12, 15)


def hex_rgb(s, fallback=(70, 70, 78)):
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return fallback
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


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

    big = pick_font(112)
    name_font = pick_font(32)
    small = pick_font(21)
    if big is None or name_font is None:
        print("找不到中文字体，跳过封面。CI 里需要 apt-get install fonts-wqy-zenhei")
        return 0

    # 竖向渐变底
    img = Image.new("RGB", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        draw.line(
            [(0, y), (W, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )

    # 两队主色各抹一团柔光，位置对角，暗示对阵关系
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    aw_r, aw_g, aw_b = hex_rgb(cv.get("away_color"))
    hm_r, hm_g, hm_b = hex_rgb(cv.get("home_color"))
    gd.ellipse([-200, -160, 400, 320], fill=(aw_r, aw_g, aw_b, 130))
    gd.ellipse([W - 400, H - 320, W + 200, H + 160], fill=(hm_r, hm_g, hm_b, 130))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    # 压一层黑，保证字够亮；压太狠会把上面那层柔光抹平
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 100))
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    draw = ImageDraw.Draw(img)

    m = 58
    draw.text((m, 40), "每日战报", font=small, fill=ACCENT)
    date_txt = cv.get("date") or ""
    if date_txt:
        tw = draw.textlength(date_txt, font=small)
        draw.text((W - m - tw, 40), date_txt, font=small, fill=DIM)

    def ink_box(text, font):
        """字形实际着墨范围。PIL 的 text() 以 ascender 顶部为 y，
        数字下面会留一大截空白，直接按字号算间距必然叠字，得用 bbox 量。"""
        return draw.textbbox((0, 0), text, font=font)

    # 大比分：客队靠左，主队靠右，中间一个冒号
    asc = str(cv.get("away_score", ""))
    hsc = str(cv.get("home_score", ""))
    score_top = 92
    ab = ink_box(asc, big)
    draw.text((m, score_top), asc, font=big, fill=INK)
    hw = draw.textlength(hsc, font=big)
    draw.text((W - m - hw, score_top), hsc, font=big, fill=INK)

    colon = ":"
    cb = ink_box(colon, big)
    cw = draw.textlength(colon, font=big)
    # 冒号在两块数字的着墨中线上居中，不是按 ascender 中线
    mid = (ab[1] + ab[3]) / 2
    draw.text(((W - cw) / 2, score_top + mid - (cb[1] + cb[3]) / 2),
              colon, font=big, fill=(96, 96, 104))

    # 队名各贴在自家比分着墨下沿
    ny = score_top + ab[3] + 30
    draw.text((m, ny), cv.get("away") or "", font=name_font, fill=INK)
    hnm = cv.get("home") or ""
    nw = draw.textlength(hnm, font=name_font)
    draw.text((W - m - nw, ny), hnm, font=name_font, fill=INK)

    # 底部一行：场次 · 标签（没有标签就只留场次）
    foot = " · ".join(x for x in (cv.get("footer") or "").split("|") if x.strip())
    if foot:
        draw.text((m, ny + ink_box("测", name_font)[3] + 30), foot, font=small, fill=DIM)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG", optimize=True)
    print(f"封面已生成：{OUT}（{OUT.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(build())
