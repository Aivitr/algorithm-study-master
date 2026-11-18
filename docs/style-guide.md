# 视觉规范（一页版）

三套页面（landing / dashboard / classroom）共用 `static/css/app.css` 的 `:root` 变量。
新代码不再写死颜色，用下列 token；历史页逐步替换。

## 字体

- 正文与标题：`'Inter'`（`/static/vendor/inter/inter.css`），回退系统字体
- 代码：`'Consolas', monospace`
- 不引入第二种无衬线字体

## 字号

常用字号用 token：`--font-xs`（12px）、`--font-sm`（14px）、`--font-base`（16px）、
`--font-lg`（18px）、`--font-xl`（20px）。大标题的 22/24/28/34px 仍按页面局部使用。

## 间距

常用间距用 token：`--space-1`（4px）、`--space-2`（8px）、`--space-3`（12px）、
`--space-4`（16px）、`--space-5`（20px）、`--space-6`（24px）、`--space-8`（32px）。
新代码不要再写这些像素值。

## 色板

| Token | 值 | 用途 |
|---|---|---|
| `--primary` | `#3E7C86` | 主色、主按钮、强调 |
| `--primary-dark` | `#2F6670` | 主色悬停/深色文字 |
| `--primary-soft` | `#E7F2F3` | 主色浅底 |
| `--accent-teal` | `#0F8B8D` | 图表/次级强调 |
| `--success` | `#4BAA7A` | 成功 |
| `--warning` | `#D9A441` | 警告 |
| `--danger` | `#D66565` | 危险操作 |
| `--danger-bg` | `rgba(220,38,38,.85)` | 危险操作叠层 |
| `--warning-bg` | `rgba(217,119,6,.9)` | 警告叠层 |
| `--text` / `--text-secondary` | `#1F2D3D` / `#6B7B88` | 主/次文字 |
| `--bg` / `--card` | `#F5F7F9` / `#FFFFFF` | 页面/卡片背景 |

## 圆角与阴影

- 小控件：`--radius-sm`（10px）；中等控件：`--radius-md`（12px）
- 卡片/输入：`--radius-lg`（16px）；大容器：`--radius-xl`（20px）
- 胶囊按钮/徽标：`--radius-pill`（999px）
- 阴影只用 `--shadow-sm/md/lg`，不新增自定义阴影

## 图标与文案

- 图标统一 Font Awesome；新控件不加 emoji
- 历史文案里的 emoji 只在改到该段时顺手移除，不做全仓批量替换
- 状态色必须同时有文字说明，不能只靠颜色区分

## 页面一致性

- landing、dashboard、classroom 的背景、卡片、按钮和文字层级使用同一套 token
- 课堂关键操作（结束课堂、停止分享、退出）使用 `--danger-bg`；小组查看提示使用 `--warning-bg`
- 新增页面先在 375px 宽度检查换行，再在桌面宽度检查顶部状态栏不重叠
