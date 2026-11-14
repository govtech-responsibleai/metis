---
name: metis-frontend-style
description: The locked house style for the METIS web app (apps/web), the HTML report (packages/insights), and the documentation site (website/). Use this skill whenever building or restyling any METIS product UI — React components, pages, dashboards, the 3-pane wizard, forms, tables — even when the user just says "build the frontend" or "make a page" without naming the style. It does not cover the marketing landing page (website/landing-page/), which follows the Landing page section of docs/design.md. It defines the palette, typography, radius, density, elevation, motion, component conventions, and copy voice so every screen looks like one deliberate product instead of a generic AI default. Built on shadcn/ui + Tailwind. Reach for it before writing any component, CSS, or Tailwind class for METIS.
---

# METIS Frontend Style

This is the house style for METIS — a measurement & evaluation platform for trustworthy AI systems. The point of this skill is that the visual direction is already decided. You are not re-inventing a look each time; you are applying one. That consistency is the whole value: a person moving between the wizard, a dashboard, and a settings page should feel they're in one product built by one team.

The brief this style answers: we are tired of UI that reads as machine-generated. The tells we named — aura/glow backgrounds, colored left-borders, uniform pillowy rounding on everything, a sea of tiny gray fine-print, boring palettes, all-caps labels, and ambient decorative animation that moves on its own. This style is defined in direct opposition to those. (Note: rounding and motion aren't banned — they're *directed*. We use two deliberate radius tiers, and motion that a user action triggers; what we reject is the undifferentiated pillowy look and animation that runs with no cause.) When you follow it, you are steering away from the default look on purpose.

## The one rule that governs everything: 95 / 5

**95% of any screen is white, near-black, and cool grey. About 5% is accent.**

Neutrals do the structural work — text, surfaces, borders, most controls. The accent is a scarce resource, spent only where it carries meaning: a selected item, a focus ring, a link, a live process. Status colours are separate, and they appear only on results. If you find navy-soft spreading across buttons, panels, and headings, you've broken the rule and the UI starts to look like every other "brand-colored" template. Scarcity is what makes the accent read as intentional.

The values live in **`docs/design.md`** in the repository. That guide is the source of truth for the brand colours, the light and dark theme, the status colours, and the data colours. Read it before you choose a colour. When you change a colour, change the token file and `docs/design.md` in the same pull request. The token files are `apps/web/src/globals.css` (web) and `PALETTE` in `packages/insights/src/metis/insights/_report_styles.py` (report).

**One product.** The web app includes the report. The report is a separate HTML file now, but it will become part of the web app, so treat the two as one product with one set of rules. The docs site (`website/src/css/custom.css`) follows the same rules, because it is for reading. It is plain: a white page (neutral black in dark mode), near-black text, and cool greys, with an occasional accent. The landing page is the dynamic, colourful surface, and its rules do not apply here.

| Role | Light | Dark | Where it's allowed |
|---|---|---|---|
| Accent | `#0A2A3D` navy-soft | `#59B9C0` light teal | selected/active state, focus rings, links, a live process. Never a pass, never a button fill |
| Gold | `#E5AE4F` | `#E5AE4F` | a rare highlight wash or marker. Too light for text on white |
| Canvas and card | `#FFFFFF` | `#0A0A0A`, `#0F0F0F` | page and panels |
| Foreground | `#0A0A0A` | `#F5F5F5` | primary text, **primary buttons** |
| Cool greys | `#5C6569` text, `#E3E7E8` line | `#A3A3A3` text, `#292929` line | everything else — the other 90% |

**Status colours.** Each result state has one colour, and the report uses the same ones. Use the token, and always add an icon, a word, or a number.

| State | Light | Dark | Web token | Report key |
|---|---|---|---|---|
| Pass | `#087F73` | `#3DB88F` | `success` | `green` |
| Fail | `#C73B45` | `#E56C74` | `fail` | `red` |
| Warning, grader error | `#B7791F` | `#DFA349` | `warning` | `amber` |
| Skipped, not graded | `#98A1AA` | `#8C8C8C` | `skipped` | `faint` |
| App error, delete | `#AB596A` | `#D78898` | `destructive` | — |

In light mode, navy-soft is close to the near-black text: the contrast between the two is only about 1.3:1. So never mark a state with accent text alone. Add a border, a left marker, or a tint as well. Dark mode keeps neutral black and grey surfaces. Do not use navy for a dark surface.

**Dark mode.** The web app has a System / Light / Dark switch at the foot of the left rail. `src/theme.ts` sets `data-theme` on `<html>`, and `index.html` sets it before the first paint. All dark values are in the one `:root[data-theme="dark"]` block. Do not add a `prefers-color-scheme` block or `dark:` classes. The report has no dark mode.

**Data colours.** Taxonomy chips use slate, periwinkle, dark gold, and green (`--tag-*`). The report heat scale goes from soft rose at 0%, through grey, to soft teal at 100% (`SCALE` in `_report_page.py`). Do not use a status colour for a chip.

The token block for both themes is in `apps/web/src/globals.css`.

## Foundations

**Typography — one sans family for each surface.** The web app uses **Figtree**. The report and the docs site use **Lato**, the Singapore Government Design System typeface. Hierarchy comes from weight and size, not from switching typefaces. Body text is 16px and secondary text is 14px. **The minimum text size is 12px**, also for chips, labels, and chart text. Use **JetBrains Mono** for anything that is data: JSON, IDs, code, metric values in tables. Never set headings in all-caps — all-caps labels are one of the clearest AI tells. Use sentence case and let size/weight create emphasis.

**Radius — two tiers, `8px` and `16px`.** Softening is intentional here, but it is *structured*: small controls get the small radius, large surfaces get the large one. Small (`--radius-sm`, `8px`) is for buttons, tooltips, badges, and small inline controls. Large (`--radius-lg`, `16px`) is for text areas, dropdowns/selects, cards, the chat composer, and floating surfaces (modals, popovers). Pick the tier by the size of the thing, then don't fine-tune per-component — two values, applied consistently, is the point. The contrast between a crisp button and a softer card is deliberate; a screen where everything shares one radius is the tell we're avoiding.

**Density — balanced.** Comfortable spacing, but efficient enough for data-heavy evaluation views. Not airy-precious, not cramped. When a screen feels busy, the fix is usually *fewer elements and less text*, not tighter spacing.

**Elevation — borders, not shadows.** Separate panels and cards with a hairline border (`--border`). Static cards get **no** shadow and **no** colored left-border. A soft shadow is permitted **only** on things that genuinely float above the page — modals, popovers, dropdowns — and, as the one in-page exception, on the read-only document sheet, where a light shadow is what marks it as a finished artifact against its pane rather than an editable field. This flat, bordered model is deliberately the opposite of the shadow-plus-glow default. And never put a blurred colored gradient "aura" behind anything.

**Motion — purposeful, and it carries continuity.** Animation communicates a state change *and* a spatial relationship: a hover, a menu opening, something loading — and, importantly, movement between screens and layouts. When the user commits to an action, let the UI *move* to reflect it: a pane the user dismisses slides out of the way; advancing to the next step slides or cross-fades the new screen in over the old. That movement tells the user where things went and where they are now — it's meaning, not decoration, and it's what makes the product feel alive rather than static. Keep it minimal and quick, and always eased: hovers/toggles 150–200ms, screen/pane transitions 200–300ms (ease-out for things entering, ease-in for things leaving). One movement per action — if two things animate at once for the same click, cut one. The line we still hold: **no ambient motion** — nothing loops, pulses, floats, or animates unless the user did something. No glow/aura, no floating blobs, no scroll-triggered flourishes. Purposeful motion reads as craft; motion for its own sake is the template look we're avoiding.

## Components

Primary/secondary/ghost buttons, inputs, cards, tables, nav, modals, and empty/loading states all have specified treatments — including which shadcn defaults to override (shadcn ships shadows and a larger radius we don't want). Read `references/components.md` before building any component so you apply the agreed structure rather than shadcn's defaults.

The single most important component decision, because it protects the 95/5 rule: **primary buttons are near-black (the foreground color), not navy-soft.** A form full of accent buttons would blow the accent budget instantly. The accent is for state, not for every call-to-action. The main action is near-black and color marks selection.

The wizard is a **3-pane layout: History │ Chat │ Profile** (experiment history left, chat centered as the main workspace, product profile right). Its shell spec is in `references/components.md`.

## Copy & voice

Words are UI, not decoration. AI-generated UI is often full of text and hard to understand, and the fix starts with the words.

- **No helper text unless it prevents a real error.** Don't explain what a well-labeled field obviously does. Every extra gray sub-line is noise.
- **Labels are 1–3 words, sentence case.** No Title Case, no ALL-CAPS, no marketing phrasing inside the product.
- **Actions are active-voice verbs, consistent across a flow.** The button says "Save"; the toast says "Saved." "Run", not "Execute experiment now".
- **Empty and error states give direction.** An empty screen invites the next action. An error says what happened and how to fix it — no vague apologies, no mood.

## Before you ship — anti-AI checklist

Run through this on any screen you build. Each item maps to a tell we want gone:

- [ ] Accent is ≤ ~5% of the screen; the rest is white, near-black, and cool grey
- [ ] Primary buttons are near-black, not navy-soft
- [ ] Every accent state has a border, marker, or tint, not accent text alone
- [ ] Panels separated by borders — no shadows on static cards, no colored left-borders
- [ ] No blurred gradient/glow "aura" behind any element
- [ ] Radius is one of the two tiers — `8px` for buttons/tooltips/small controls, `16px` for text areas/dropdowns/cards/floating surfaces — no ad-hoc third value
- [ ] No ALL-CAPS headings or labels; sentence case throughout
- [ ] Motion is tied to a user action — panes/screens move to show where things went; nothing loops, pulses, or floats on its own; no glow, no scroll flourishes
- [ ] No sea of gray helper text; every word earns its place
- [ ] No text is smaller than 12px
- [ ] Type is Figtree in the web app and Lato in the report and the docs (+ JetBrains Mono for data); hierarchy from weight/size, not extra typefaces
- [ ] Pass, fail, warning, and skipped use the status tokens, with an icon or a word; the accent never means pass
- [ ] The screen works in both light and dark themes

If any box fails, fix it before calling the screen done. These aren't style preferences layered on top — they *are* the style.
