# METIS Components — shadcn overrides & specs

shadcn/ui is the base, but its defaults fight this style in two predictable ways: it ships **shadows** on cards/buttons/popovers, and a **single larger radius** (`0.5rem`) on everything. The token file replaces that with two tiers — `--radius-sm` (`8px`) for small controls, `--radius-lg` (`16px`) for large surfaces. When you add or hand-write a component, pick the tier by the size of the element (see each section below). The notes below fix the rest, component by component. Apply these when you `npx shadcn add` a component or hand-write one.

The through-line: neutrals carry structure, borders carry separation, navy-soft carries state. Re-read the 95/5 rule in SKILL.md if any choice here tempts you toward more color.

## Buttons

Three tiers, and the hierarchy is by weight, not color.

| Tier | Treatment | Use |
|---|---|---|
| Primary | Solid **near-black** (`bg-primary text-primary-foreground`) | The main action on a screen |
| Secondary | Bordered, transparent fill (`border bg-transparent`) | Alternative / secondary actions |
| Ghost | Text only, subtle hover fill (`hover:bg-muted`) | Tertiary, toolbar, low-emphasis actions |

- **Do not** make primary buttons navy-soft. Accent buttons break the accent budget the moment a form has more than one. The strong neutral is the CTA; navy-soft marks *state*, not *action*.
- Prefer **one primary button per screen** — it's the clearest way to signal the main path. Extra emphatic buttons dilute the hierarchy.
- Remove any default shadow shadcn adds (`shadow-sm`). Buttons are flat.
- Focus: navy-soft ring (`focus-visible:ring-2 ring-ring`) — this is a correct, on-budget use of the accent.

## Inputs & forms

- Hairline border (`border-input`), transparent/`bg-background` fill. Radius: single-line inputs and the like take the **small** tier; multi-line text areas and dropdown/select surfaces take the **large** tier (`rounded-lg`).
- **Label above the field**, always. Not floating, not inline. Sentence case, 1–3 words.
- Focus: navy-soft ring. This is often the *only* accent on a form — that's intended.
- **No helper text** under a field unless it prevents a real error (format hint, constraint). A well-labeled field needs no explainer.
- Validation errors appear on submit/blur, stated plainly (see Copy in SKILL.md), in `text-destructive`.
- Group related fields with spacing, not boxes-within-boxes. Nesting bordered cards inside bordered cards reads as clutter.

## Cards & panels

- Separation is a **border** (`border rounded-lg` — cards are a large surface), never a shadow, never a colored left-border.
- No `shadow-sm`/`shadow` — strip it from the shadcn Card default.
- Header/body/footer separated by internal borders or spacing, not elevation.
- Don't reach for a card just to group two fields. Cards are for genuinely distinct regions.

## Tables (evaluation data)

Data density lives here, so restraint matters most.

- Header row: `text-muted-foreground`, medium weight, sentence case, **not** all-caps.
- Row separation: hairline bottom borders, not zebra fills (a very subtle `--muted` stripe is acceptable if rows are dense and hard to track).
- Numeric/metric/ID cells: **JetBrains Mono**, right-aligned for numbers.
- Status via a small icon or text in the status colour (`text-success`, `text-fail`, `text-warning`, `text-skipped`) or a quiet badge — not a full colored row.
- Keep row height tight but tappable; avoid oversized padding that pushes data off-screen.

## Navigation

- Left rail or top bar in neutrals.
- **Selected item** is where navy-soft earns its place: a navy-soft left-marker or tint on the active item. Accent text alone is too close to the near-black text to read as a state. Everything unselected stays neutral. This is the canonical 5% use.
- No shadows under the nav; a border divides it from content.

## Modals, popovers, dropdowns (the only place shadows live)

- These genuinely float, so a **soft shadow is allowed** to lift them off the page — plus a border.
- Keep the shadow soft and neutral; no colored glow.
- Overlay scrim: low-opacity neutral, not a blurred colored wash.
- Radius: **large** tier (`rounded-lg`) — these are large floating surfaces.

## Empty & loading states

- **Empty**: one line saying what's missing + one clear action (usually a primary button). It's an invitation, not decoration. No giant illustration, no glow.
- **Loading**: neutral skeletons (subtle `--muted` blocks) or a small spinner. Fast, quiet. A navy-soft progress/active indicator is fine — that's meaningful state.
- **Error**: what happened + how to fix, in `text-destructive` or a bordered neutral panel. No apology copy, no mood.

## Status & badges

- Default badges are neutral (bordered or `--muted` fill).
- **Accent** badge/dot: active, running, selected. The accent never means pass.
- **Status colours** for results, from `docs/design.md`: `success` for a pass, `fail` for a failed result, `warning` for a warning or a grader error, `skipped` for skipped or not graded. Always pair the colour with a Lucide icon (`Check`, `X`, `TriangleAlert`, `Minus`), a word, or a number. Do not use text characters such as ✓ or ⚠ as icons.
- **Rose** (`destructive`): an app error, a failed request, and a delete.
- **Gold** wash: reserve for the rare thing that must stand apart (e.g. a "featured"/"baseline" marker). Using it everywhere defeats its purpose.
- Never more than one accent color competing in the same cluster.

## Wizard shell (3-pane)

The core METIS surface. Layout, left → right:

```
┌──────────────┬───────────────────────────┬──────────────┐
│  History     │           Chat            │   Profile    │
│  (experiment │      (main workspace)     │  (product    │
│   history)   │                           │   profile)   │
└──────────────┴───────────────────────────┴──────────────┘
```

- **History (left):** list of past experiments. Selected experiment marked with navy-soft (the nav pattern above). Neutral otherwise.
- **Chat (center):** the primary workspace, widest pane. Message thread + composer at the bottom. Composer is a bordered input; send is a **near-black** primary button (not navy-soft). Keep chrome minimal — the conversation is the content.
- **Profile (right):** the product profile being evaluated. Read-mostly reference; neutral, bordered sections, mono for any IDs/config values.
- **Panes divided by hairline borders**, not shadows or gaps-with-elevation. Use a resizable panel primitive (e.g. `react-resizable-panels`, which shadcn wraps) so widths adjust; keep the drag handle a subtle neutral line that hints navy-soft on hover.
- Responsive: below a wide breakpoint, collapse side panes into toggles/tabs rather than cramming three columns — the chat keeps priority.

## Motion & transitions

Motion here is minimal but load-bearing: it shows the user where things went. Every animation is triggered by a user action — never idle, never looping.

- **Durations & easing.** Hovers, toggles, small state changes: 150–200ms. Pane and screen transitions: 200–300ms. Enter with ease-out, leave with ease-in (`ease-in-out` is fine for symmetric moves). Respect `prefers-reduced-motion` — drop to an instant/opacity-only change when the user asks for less motion.
- **Dismissing a pane.** When the user collapses or closes a side pane (History/Profile in the wizard shell), it **slides out** toward its edge (translate + fade) and the remaining panes take the space. Reopening slides it back in from the same edge. The direction is the spatial cue — a pane that left rightward returns from the right.
- **Advancing between screens/steps.** Moving forward slides the new screen in from the right as the old leaves left (or a cross-fade for a lighter feel); moving back reverses it. The old and new screen share the transition so it reads as one movement, not two. Keep it to a single directional metaphor across a flow.
- **Buttons committing to a change.** A click that advances the flow hands off to the screen transition above — the button itself doesn't need its own animation on top. A quiet press feedback (subtle background/opacity shift, no bounce/scale-spring) is enough for the button.
- **Menus, popovers, dropdowns.** Fade + small scale/translate from their anchor (e.g. `100ms` in, slightly faster out). They open from where they were triggered, not from screen center.
- **One movement per action.** If a click would animate two things at once, pick the one that carries the meaning and make the other instant. Competing animations read as busy.
- **What stays banned.** No looping/pulsing/floating elements, no glow or aura, no scroll-triggered reveals, no decorative entrance animations on static content that just loaded. If it isn't the direct result of something the user did, it doesn't move.
- **Implementation.** Prefer CSS transitions for hovers/toggles and a small animation primitive (e.g. `framer-motion` / `tailwindcss-animate`) for enter/leave and shared layout transitions; `AnimatePresence`-style mount/unmount handles the slide-out-then-remove case cleanly.

## Quick self-check for any component

Before considering a component done, confirm: borders (not shadows) separate it, radius is the right tier for its size (`8px` small controls / `16px` large surfaces), any color on it is a meaningful state (not decoration), labels are sentence case, and no helper text is doing nothing. If it would look at home in a generic AI-generated dashboard, something above was skipped.
