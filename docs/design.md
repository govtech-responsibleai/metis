# METIS design guide

METIS has two surfaces. The landing page tells people what METIS is and why they should try it.
The web app is where they use it. The evaluation report belongs to the web app. Today it is a
separate HTML file, but we plan to move it into the web app, so we design it with the same rules.
The documentation site is for reading, so it follows the web app rules too.

Each surface keeps its colours in one token file, and components read their colours from these
tokens. If you change a token, update this guide in the same pull request.

| Surface | Token file |
|---|---|
| Landing page | `website/landing-page/src/index.css` (`:root`) |
| Web app | `apps/web/src/globals.css` (`:root` and `:root[data-theme="dark"]`) |
| Web app, report | `PALETTE` in `packages/insights/src/metis/insights/_report_styles.py` |
| Web app, docs | `website/docs/src/css/custom.css` (a copy of the web app tokens) |

## Brand colours

The brand colours come from the METIS seal. The landing page uses all of them. The web app uses
navy-soft as its accent, and it uses rose, periwinkle and gold in a few small places.

| Name | Value | Use |
|---|---|---|
| Navy | `#021220` | The landing page hero |
| Navy-soft | `#0A2A3D` | The landing page hero gradient, and the web app accent |
| Gold | `#E5AE4F` | Landing page buttons and highlights, and a rare wash in the web app |
| Gold-dark | `#9B7520` | Landing page section labels |
| Paper | `#FAF8F3` | The landing page background |
| Periwinkle | `#3C468B` | Landing page art, and a web app chip |
| Rose | `#AB596A` | Landing page art, and web app errors and delete |
| Peach | `#F6D6CB` | Landing page washes |
| Green | `#5E9B6D` | Landing page art |

## Landing page

The landing page is the colourful part of METIS. It opens on a navy hero, with trace art that moves
slowly behind the text, and the sections below it sit on warm paper. The headline has a phrase in
gold serif italic. Buttons are gold on the navy hero and navy on paper. Gold is too light to read
as text on paper, so the section labels there use gold-dark.

## Web app

People use the web app for long sessions, so we keep it quiet. Most of the screen is white,
near-black and cool grey. Thin borders separate the panels, and light shadows lift the things that
float, such as menus and dialogs. We use the accent sparingly, to mark the selected item or the
focused field, so the screen stays minimal.

The web app uses Figtree, and the report and the docs use Lato. Numbers and code use JetBrains
Mono. The smallest text size is 12px.

Dark mode uses neutral black and grey. The user picks System, Light or Dark at the foot of the left
rail. The docs site follows the system setting, and its navbar switch changes it. The report has no
dark mode yet.

The tables below give the colours for the surfaces, the result states and the data.

### Surfaces and text

| Role | Light | Dark |
|---|---|---|
| Page | `#FFFFFF` | `#0A0A0A` |
| Card | `#FFFFFF` | `#0F0F0F` |
| Muted fill (rail, table header) | `#F3F5F6` | `#1C1C1C` |
| Text | `#0A0A0A` | `#F5F5F5` |
| Muted text | `#5C6569` | `#A3A3A3` |
| Line | `#E3E7E8` | `#292929` |
| Primary button | `#171717`, white text | `#F5F5F5`, near-black text |
| Accent | `#0A2A3D` navy-soft | `#59B9C0` light teal |

### Status colours

Each result state has its own colour and a Lucide icon.

| State | Light | Dark | Token | Report key | Lucide icon |
|---|---|---|---|---|---|
| Pass | `#087F73` | `#3DB88F` | `success` | `green` | `Check` |
| Fail | `#C73B45` | `#E56C74` | `fail` | `red` | `X` |
| Warning, grader error | `#B7791F` | `#DFA349` | `warning` | `amber` | `TriangleAlert` |
| Skipped, not graded | `#98A1AA` | `#8C8C8C` | `skipped` | `faint` | `Minus` |
| App error, delete | `#AB596A` | `#D78898` | `destructive` | — | — |

The report fills its result cells with soft versions of these colours.

| Fill | Background | Text |
|---|---|---|
| Pass | `#E0F0EC` | `#0B6B5C` |
| Fail | `#F2CFD2` | `#A3262F` |
| Skipped | `#F1F2F2` | muted text |
| Errored | `#F7ECD6` | text |

### Data colours

The report shows each pass rate on a heat scale from soft rose to soft teal (`SCALE` in
`_report_page.py`).

| 0% | 25% | 50% | 75% | 100% |
|---|---|---|---|---|
| `#F2CFD2` | `#F6E6E7` | `#F1F2F2` | `#E0F0EC` | `#C6E6DE` |

Each taxonomy chip on a grader row has its own quiet hue.

| Field | Light | Dark |
|---|---|---|
| Type | `#2F556A` slate | `#8DB2C3` |
| Scope | `#3C468B` periwinkle | `#A3ABE0` |
| Reference | `#856319` dark gold | `#E4AD4E` |
| Judgment | `#4A7D57` green | `#8CC59A` |
