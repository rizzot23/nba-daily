# 去球吧 · 品牌资产

## 文件

| 文件 | 用途 |
|---|---|
| `sheet.html` | **先看这个**，一页规范：主形象、推导、三版标志、两个头像、尺寸测试、色值、规矩 |
| `brand-brief.md` | 设计简报：七个要素、场景约束、取舍理由 |
| `mark.json` | 标志的唯一数据源（3 个图元的坐标）。改了它就跑脚本重生成，别手改 SVG |
| `render_assets.py` | 渲染 PNG 资产（头像、标记、横排组合、场景模拟） |
| `fonts/SmileySans-Oblique.ttf` | 得意黑，SIL OFL 1.1，可商用。字标专用 |
| `reference.png` | 参考视觉原图，所有几何比例都从它量出来 |
| `dist/` | mark-to-spec 生成的技术规范（SVG 三版、净空图、尺寸测试、spec.html） |
| `out/` | 实际要上传的 PNG |

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

- 公众号头像：`out/avatar-wood-640.png`（备选 `out/avatar-640.png`）
- 头条号头像：同上，一张两用
- 正文页眉：`out/lockup.png`（深底用 `out/lockup-reverse.png`）
- 封面角标：`out/mark-reverse-512.png` 叠在拼色带上
