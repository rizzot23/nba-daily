# 去球吧 · 品牌资产

**当前：v4 文字标志**（只用得意黑排字，不画图）。头像用「球吧」两字，字标用「去球吧」三字。

| 版本 | 参考 | 画法 | 目录 | 状态 |
|---|---|---|---|---|
| v1 | `reference.png`（篮筐 + 球） | 几何化 | `out/` | 归档 |
| v2 | `reference2.png`（双色地 + 球压线） | 几何抽象 | `out2/` | 归档 |
| v3 | 同 v2 | 照片简笔画（橙球 + 四条球缝） | `out3/` | 归档（用户认为图形不成） |
| v4 | — | **文字标志**，只排字 | `out4/` | **当前** |

v1–v3 都是图形标志，全部被否；v4 放弃画球，只做字。为什么：图形标志要在一个圆里同时说清"这是篮球"和"这是去球吧"，信息太多；纯字标只承担一件事——让人记住这四个字的形状。

## 文件

| 文件 | 用途 |
|---|---|
| `sheet.html` | **先看这个**，一页规范：主形象、推导、三版标志、两个头像、尺寸测试、色值、规矩 |
| `brand-brief.md` | 设计简报：七个要素、场景约束、取舍理由 |
| `brand-compare.png` | 照片 / v2 / v3 三方对照 |
| `mark.json` | v1 标志的数据源（3 个图元的坐标） |
| `render_assets.py` | v1 渲染 |
| `render_v2.py` | v2 渲染（几何抽象版） |
| `render_v3.py` | v3 渲染（照片简笔画版，**当前主用**） |
| `fonts/SmileySans-Oblique.ttf` | 得意黑，SIL OFL 1.1，可商用。字标专用 |
| `reference.png` / `reference2.png` | 参考视觉原图，比例全从它们量出来 |
| `dist/` | v1 的技术规范（SVG 三版、净空图、尺寸测试、spec.html） |
| `out/` `out2/` `out3/` | 实际要上传的 PNG |

## 重新生成

```bash
# 技术规范（SVG / 尺寸测试 / 净空图）
python "$HOME/.workbuddy/plugins/marketplaces/experts/plugins/logo-editorial-designer/skills/mark-to-spec/scripts/mark_spec.py" \
  --config brand/mark.json --outdir brand/dist --check-mono

# PNG 资产
python brand/render_assets.py
```

## 核心比例（别凭手感改）

```
环    中心 (33, 28.5)  rx 18  ry 11.7  线宽 3.6   ← 参考图实测 1.54:1
球    中心 (64, 64)    r 17                       ← 参考图实测 0.36W
地线  y 81  x 12→88    线宽 3.2                   ← 与球底相切
字    球  墨迹高 40，底边贴 79.2（地线上缘）
```

头像版只把「实心球面」换成「球」字，其余坐标不动。想调比例，改 `mark.json` 和 `render_assets.py` 顶部的常量，两处要保持一致。

## 上传

**v4（当前）**
- 公众号头像 / 头条号头像：`out4/v4-avatar-640.png`（同一张，两号通用）
- 字标（透明底墨色）：`out4/v4-wordmark-640.png`，深底用 `-reverse-640.png`
- 横排组合（字标 + NBA 每日战报）：`out4/v4-header.png`
- 深底头像：`out4/v4-avatar-reverse-640.png`；单色：`out4/v4-avatar-mono-640.png`

> 字标是 1435×640 的透明 PNG，插在正文里按 CSS 高度 90–120px 用；1x 屏直接缩，高密度屏靠 Pillow 的 LANCZOS 也够，不必另出 2 倍图（矢量笔画放大到 120px 仍然干净）。

**v3（已归档，不再使用）**
- 公众号头像 / 头条号头像：`out3/v3-avatar-640.png`（同一张，两号通用）
- 正文页眉：`out3/v3-lockup-1200.png`（放 CSS 宽度 400–500px；深底用 `-reverse-1200.png`）
- 封面角标：`out3/v3-mark-256.png` 叠在拼色带上
- 单色 / 水印：`out3/v3-mono-512.png`

> 页眉为什么要用 1200 那张：微信正文按 CSS 像素排版，但高密度屏是 2–3 倍像素密度，807px 的图放在 400px 宽的位置上等于 2 倍图勉强够、3 倍屏会发虚。1213×552 放 400–500px 正好落在 2.4–3 倍之间。

**注意：`docs/report.html` 的页眉保持纯文字**（“去球吧 · NBA 每日战报”一行），2026-11-03 决定。原因：这份 HTML 是粘贴进公众号编辑器的，公众号不认相对路径的图，粘过去会掉，得每次手动传一次 logo。为了每天少一步手动，页眉不插图；字标只用在封面、头像和单独插图的位置。

## v3 字标组合的结构（已归档，留作参考）

v4 只有纯字，v3 那套的构图逻辑不再沿用，但记下来免得重复试错：

```
[标志 184px]  [去球吧 74px]
              ← 手绘黄划（两头收细、中间最粗、微翘 3°）
              [NBA 每日战报 26px + 1.4 字距]
```

黄划是 v3 全套资产里唯一的笔触装饰，别在小字上再加第二个（胶囊、下划线都试过，见 `README-v3.md`）。改粗细改 `_swipe()` 里第一个数字（现在是 `9*scale`）。

**v1（备选）**
- 公众号头像：`out/avatar-wood-640.png`（备选 `out/avatar-640.png`）
- 正文页眉：`out/lockup.png`（深底用 `out/lockup-reverse.png`）
- 封面角标：`out/mark-reverse-512.png`
