---
status: pending
priority: p2
issue_id: "002"
tags: [code-review, frontend, assets, agent-native]
dependencies: []
---

# Specify exact sources for fonts, chart library, and table library

## Problem Statement

The plan names assets (Fraunces, Geist, JetBrains Mono, Lightweight
Charts v5.2, Tabulator v6.4) but doesn't say *where to get them*. An
agent dispatched via `/ce:work` cannot translate `font-family: 'Geist'`
to working CSS without a `@font-face` block or a `<link>` tag with a
specific URL. Same for the JS libraries — should the agent download
from unpkg, jsDelivr, or the GitHub release?

The plan also says "SRI on CDN assets" — but if the assets are
committed locally (recommended), SRI is moot.

## Findings

- **Source:** agent-native-reviewer (Finding #2 + #3).
- Without this spec, an agent will either guess (likely picking an
  outdated CDN URL) or stop and ask the user.

## Proposed Solutions

### Option A — All assets committed locally (Recommended)

Download once at Phase 2 setup; commit to `docs/assets/`. No CDN
trust, no SRI needed, no runtime network calls beyond the page itself.

- **Lightweight Charts:** `https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js` → `docs/assets/lightweight-charts.standalone.production.js`
- **Tabulator JS:** `https://unpkg.com/tabulator-tables@6.4.0/dist/js/tabulator.min.js` → `docs/assets/tabulator.min.js`
- **Tabulator CSS:** `https://unpkg.com/tabulator-tables@6.4.0/dist/css/tabulator.min.css` → `docs/assets/tabulator.min.css`
- **Fraunces:** Google Fonts CSS link OR self-host the variable woff2 from `https://fonts.gstatic.com/s/fraunces/...`
- **JetBrains Mono:** `https://github.com/JetBrains/JetBrainsMono/releases/latest` → self-host variable woff2
- **Geist:** `https://github.com/vercel/geist-font/releases/latest` → self-host woff2 (no Google Fonts version)

**Pros:** Reproducible, no CDN trust, no SRI ceremony, works offline.

**Cons:** Slightly more page weight (browsers can't dedupe across
sites). For a small public site, negligible.

**Effort:** Small (one-time download + commit).

### Option B — Google Fonts link for fonts; locally commit JS

**Pros:** Google Fonts auto-optimizes subsets.

**Cons:** External dep, breaks offline dev, browser caches by origin
not by font.

**Effort:** Small.

## Recommended Action

(Filled during /ce:work — likely Option A.)

## Technical Details

**Affected files (new):**
- `docs/assets/lightweight-charts.standalone.production.js`
- `docs/assets/tabulator.min.js`
- `docs/assets/tabulator.min.css`
- `docs/assets/fonts/Fraunces.woff2`
- `docs/assets/fonts/JetBrainsMono.woff2`
- `docs/assets/fonts/Geist.woff2`
- `docs/assets/style.css` — `@font-face` block referencing the above
- `templates/base.html.j2` — `<link rel="stylesheet" href="/assets/style.css">`

**Affected plan section:** Frontend Design Tokens appendix needs an
"Asset sources" subsection.

## Acceptance Criteria

- [ ] All asset files committed under `docs/assets/`
- [ ] `style.css` has `@font-face` for all three fonts with
      `font-display: swap`
- [ ] Every page loads in <2s on a 4G cold cache (proxy: no CDN waits)
- [ ] No runtime requests to fonts.googleapis.com, unpkg.com, or
      jsdelivr.net in DevTools Network tab
- [ ] Plan's Frontend Design Tokens appendix updated with exact URLs

## Work Log

(empty)

## Resources

- Geist Font: https://vercel.com/font
- Fraunces: https://fonts.google.com/specimen/Fraunces
- JetBrains Mono: https://www.jetbrains.com/lp/mono/
- Lightweight Charts releases: https://github.com/tradingview/lightweight-charts/releases
- Tabulator releases: https://github.com/olifolkerd/tabulator/releases
