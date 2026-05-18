# 玄枢 XuanShu Logo System

## Brand Idea

玄枢是一个本机智能中枢。标志用一个抽象的“枢轴”表达三层含义：

- 中央核心：本机智能内核。
- 断裂轨道：工具、记忆、桌面、浏览器、终端和工作流围绕核心协同。
- X 形轴线：呼应 XuanShu 的 X，也表达可执行、可转向、可调度的 Agent 能力。

## Assets

- `xuanshu-icon.svg`：暗色主应用图标，适合 app icon、托盘、favicon、启动页。
- `xuanshu-icon-light.svg`：浅色应用图标，适合亮色设置页、文档、安装器和浅色窗口标题栏。
- `xuanshu-icon-mono.svg`：单色版本，适合小尺寸、蒙版、压印、深色 UI 中的弱化标记。
- `xuanshu-wordmark-dark.svg`：深色横版主标，适合 README、官网首屏、安装器。
- `xuanshu-wordmark-light.svg`：浅色横版主标，适合文档、白底页面、演示材料。
- `xuanshu-preview.html`：品牌预览页。

## Colors

| Token | Hex | Source | Usage |
| --- | --- | --- | --- |
| Dark App | `#0D1117` | `--bg-app` dark | Dark logo background |
| Dark Surface | `#161B22` | `--bg-surface` dark | Embedded UI surfaces |
| Dark Border | `#30363D` | `--border-default` dark | Logo frame and separators |
| Dark Text | `#E6EDF3` | `--text-primary` dark | Dark wordmark text |
| Dark Accent | `#58A6FF` | `--accent-rgb` dark | Primary dark logo motion |
| Dark Accent Strong | `#388BFD` | `--accent-emphasis-rgb` dark | Axis endpoint |
| Dark Success | `#3FB950` | `--success-rgb` dark | Live core dot |
| Light App | `#FFFFFF` | `--bg-app` light | Light logo background |
| Light Surface | `#F3F3F3` | `--bg-surface` light | Light icon tile surface |
| Light Border | `#D4D4D4` | `--border-default` light | Light logo frame |
| Light Text | `#1E1E1E` | `--text-primary` light | Light wordmark text |
| Light Accent | `#0067B8` | `--accent-rgb` light | Primary light logo motion |
| Light Accent Strong | `#005A9E` | `--accent-emphasis-rgb` light | Axis endpoint |
| Light Success | `#1F883D` | `--success-rgb` light | Live core dot |

## Theme Fit

The logo variants intentionally map to the product's existing theme tokens:

- Dark assets sit on `#0D1117`, use `#30363D` for borders, `#E6EDF3` for text, and the product blue `#58A6FF` for the axis/rings.
- Light assets sit on `#FFFFFF` / `#F3F3F3`, use `#D4D4D4` for borders, `#1E1E1E` for text, and the product blue `#0067B8` for the axis/rings.
- Green is only a small state accent, matching the app's success color and avoiding a separate competing brand palette.

## Typography

- Chinese: HarmonyOS Sans SC, Source Han Sans SC, Microsoft YaHei.
- Latin: Inter, Geist, IBM Plex Sans, Arial fallback.
- Preferred lockup: `玄枢` above `XuanShu`, with `Local Agent OS` as the technical descriptor.

## Usage Rules

- Keep the icon simple at small sizes. Do not add extra orbit lines or text inside the app icon.
- Use the dark version for product surfaces and the light version for documents.
- Do not replace the center core with a robot, brain, or chat bubble.
- Do not use mystical imagery such as talismans, compasses, or traditional diagrams.
- Leave at least one icon-core radius of clear space around the logo.
