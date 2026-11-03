# 去球吧 · 品牌资产

**定稿：v4 文字标志**（2026-11-03）。只用得意黑排字，不画图形。

| 件 | 样子 | 用在哪 |
|---|---|---|
| 头像 | 皮棕圆 `#D9925A` + 「球吧」两字，墨色 | 公众号 / 头条号头像 |
| 字标 | 「去球吧」三字横排，墨色，透明底 | 封面、页眉插图、文末署名 |

## 上传

| 文件 | 用途 |
|---|---|
| `out4/v4-avatar-640.png` | **头像**，两个号同一张 |
| `out4/v4-wordmark-640.png` | 字标，透明底；深色背景用 `-reverse-640.png` |
| `out4/v4-header.png` | 字标 +「NBA 每日战报」小字，页眉插图 |
| `out4/v4-avatar-reverse-640.png` | 深底头像（墨底棕字） |
| `out4/v4-avatar-mono-640.png` | 单色，墨底纸白字 |

字标按 CSS 高度 90–120px 用；笔画是矢量导出的，放大到 120px 仍干净，不必另出 2 倍图。
`brand-final.png` 是这五件排在一页的汇总，要传东西看那一张就够。

`out4/` 里还有 32–320px 的多档头像，按平台要求取，一般只用 640 那张。

## 文件

| 文件 | 是什么 |
|---|---|
| `wordmark.py` | 唯一脚本。生成 `out4/` 全部资产 |
| `README-v4.md` | 设计说明：为什么头像只用两字、光学字距、底色为什么是皮棕 |
| `brand-brief.md` | 设计简报：事实表、场景约束、48px 底线 |
| `brand-final.png` | 一页定稿汇总 |
| `reference2.png` | 参考照片，皮棕 `#D9925A` 从这里取样 |
| `fonts/SmileySans-Oblique.ttf` | 得意黑，SIL OFL 1.1，可商用。**不在版本库里**（4.5MB，见 `.gitignore`）。换机器时从 [atelier-anchor/smiley-sans 的 Releases](https://github.com/atelier-anchor/smiley-sans/releases) 下压缩包，取出 `.ttf` 放进 `brand/fonts/` |

## 重新生成

```bash
python brand/wordmark.py
```

改底色改 `wordmark.py` 里的 `LEATHER`；改字距改 `GAPS`；改头像留白改 `AV_INSET`。三个常量的取值理由都写在 `README-v4.md` 里。

## 已经不用的方案

v1（篮筐 + 球，几何化）、v2（双色地 + 球压线，几何抽象）、v3（同一张照片画成简笔画）都是图形标志，**2026-11-03 全部作废**，代码与导出图已从工作区删除。

作废的共同原因：图形标志要在一个圆里同时说清「这是篮球」和「这是去球吧」，信息超载；纯字标只承担一件事——让人记住这三个字的形状。最终头像连球都不画，只用篮球自己的颜色。

要翻旧版，看 git 历史，删除前的最后一个提交往前的记录里都有。
