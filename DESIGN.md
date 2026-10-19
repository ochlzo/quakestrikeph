---
name: QuakeStrike PH Bulletin
description: White and teal interfaces for Philippine earthquake information
colors:
  action-teal: "#0e6873"
  dark-text: "#1a2c30"
  supporting-charcoal: "color-mix(in srgb, #1a2c30 70%, #ffffff)"
  page-canvas: "#fafafa"
  white-surface: "#ffffff"
  app-border: "#e5e5e5"
  selected-teal-tint: "color-mix(in srgb, #0e6873 10%, #ffffff)"
  error-red: "#e4201b"
  ocean-blue: "#74A9D9"
rounded:
  control: "12px"
  panel: "16px"
components:
  button-primary:
    backgroundColor: "{colors.action-teal}"
    textColor: "{colors.white-surface}"
    rounded: "{rounded.control}"
  event-selected:
    backgroundColor: "{colors.selected-teal-tint}"
    textColor: "{colors.dark-text}"
---

# QuakeStrike PH UI design

## Overview

Use white surfaces, teal actions, pale teal selection, and dark charcoal text. The interface prioritizes earthquake information and clear tasks.
The implemented visual theme is light. Preserve the existing identity when extending Bulletin or the private alert-testing tool.

Use these sources before adding styles or components:

| Area | Source |
| --- | --- |
| Shared colors, fonts, and radius scale | [Shared theme](packages/ui/theme.css) |
| Shared controls, logo, and feedback | [UI package](packages/ui/) |
| Bulletin layout and scoped map styles | [Global styles](apps/quakestrikeph-bulletin/src/styles/globals.css) |
| Account layout and controls | [Account styles](apps/quakestrikeph-bulletin/src/styles/accounts.css) and [account flow styles](apps/quakestrikeph-bulletin/src/styles/account-flow.css) |
| Forecast layout | [Forecast styles](apps/quakestrikeph-bulletin/src/styles/forecast.css) |
| Product meaning and terminology | [PRODUCT.md](PRODUCT.md) and [GLOSSARY.md](GLOSSARY.md) |

The frontmatter lists core visual values. Source tokens and component variants define exact sizes and screen-specific overrides.

## Colors

- Use teal for primary actions and navigation, pale teal for selection, and charcoal for readable text.
- Use red for errors and green icons for successful actions. Pair status colors with text or an icon.
- Preserve the map's scoped palette and ocean blue. Geographic labels retain the basemap's native styling.
- Observed earthquake markers use the existing categorical magnitude colors and uniform sizes. Selection adds an inset ring.
- Magnitude colors describe observed magnitude, not local shaking, damage, or forecast probability. The highest band includes magnitude 6.0.

## Typography

Use Geist Variable with a sans-serif fallback for interface text, including map controls. Basemap labels retain provider fonts.
Use compact bold headings, readable body text, and quieter supporting text. Reuse the relevant component's typography rather than applying one size everywhere.

Keep labels, values, and units together. Allow long locations and field messages to wrap on narrow screens.
Show earthquake and forecast times in Philippine time, with enough context to distinguish the event time and forecast window.

## Layout

### Bulletin

Above 760px, use the floating results sidebar beside the header and map. Search and filters remain above independently scrolling results.
Keep Earthquakes and About centered in the desktop header, with the session-aware alert action separate.

At 760px and below, use the compact header, overlay navigation, and bottom earthquake drawer.
The drawer keeps the map interactive and exposes the selected event, Forecast Overview, or searchable results.
Preserve selection and filters when drawers close or the viewport crosses the breakpoint.
Map controls, attribution, and selected content must remain reachable as the drawer changes height.

### Accounts

Above 760px, settings and their phone/password steps share the desktop settings Dialog over an inactive Bulletin.
Keep the settings rail and close control visible while the content panel scrolls. Outside clicks do not dismiss the Dialog.
Direct visits and refreshes retain the Bulletin background. Preserve the mounted settings state across viewport changes.

At 760px and below, settings fill the viewport with their header and destination tabs.
Short account forms start near the top on a white surface. Hide decorative panels and omit unnecessary outer cards.
Keep fields left-aligned and allow scrolling when the keyboard opens. Reuse the existing narrow form column for phone, password, and verification steps.

### Forecasts

Keep event facts, the original forecast window, and model estimates distinct.
Use persistent section navigation with native links. All explanation sections remain visible as the reader scrolls.
Desktop pairs explanation graphics with text; mobile places graphics above text and includes the activity map in section navigation.

Use one reading column when no forecast is available. Include the observed event time, source link, and public availability explanation.

## Elevation & Depth

Use borders and tonal surfaces to separate groups. Reserve soft shadows for floating controls and overlays.
Keep terrain and native sky effects inside the map. Reuse existing basemap treatment and attribution.

## Shapes

Use the shared radius scale and existing component variants. Account fields and Bulletin filters use 12px corners; panels commonly use 16px corners.
A compact shared Button and a full-width form action have different sizes. Reuse the screen's established sizing and touch targets.
Keep interactive touch areas at least 44px where the existing mobile controls use extended targets.

## Components

### Shared components

Reuse `@quakestrikeph/ui` controls through the application's existing imports. Extend shared components when multiple screens need the same change.
Use imported Lucide icons and accessible names for icon-only controls. Preserve keyboard operation, focus visibility, and reduced-motion behavior.

Use [Logo](packages/ui/logo.tsx) for the Earth mark, QuakeStrike PH name, and subtitle.
The default subtitle is Bulletin; the private tool uses Alert testing.
Use [Search](packages/ui/search.tsx) for province and alert-location searches. Each feature owns its queries, suggestions, and errors.

### Search, filters, and selection

Keep typed province search separate from its applied filter. Fewer than two trimmed characters leave the applied search unchanged.
Date and magnitude filters share a row. Magnitude supports multiple bands, with All magnitudes as the default when no band remains selected.

Keep list and map selection synchronized. Selected event facts include observed magnitude, location, Philippine time, depth, source, and a forecast link.
Preserve the API location wording apart from removing leading zeroes from the initial kilometre distance.

### Maps and forecasts

Markers represent observed earthquakes. Show an activity-radius circle only when a valid positive forecast radius is available.
The circle estimates the spread of further activity; it is neither a shaking map nor a safe boundary.
Desktop places Forecast Overview inside the map; mobile places the overview in the existing earthquake drawer.

Forecast facts lead with the chance of further activity at magnitude 1.0 or higher.
Keep probabilities separate from count, magnitude, and radius estimates. Preserve conditions, uncertainty, and explanations.

Replay shows observations only through Now. Its selected range and zoom do not alter the original forecast window.
Preserve both range handles, the forecast-end playback pause, and the final stop at Now.
On forecast maps, inspecting another observed marker preserves the anchor selection. Recenter returns to the anchor; Bulletin recenter remains Philippines-wide.
Use [ForecastPage](apps/quakestrikeph-bulletin/src/components/ForecastPage.astro) and existing replay components for detailed interaction behavior.

### Accounts and feedback

Public reading requires no account. The alert action leads signed-out readers to sign-in and signed-in readers to Alert settings.
Keep channel opt-ins independent from destination verification. Email change and account removal remain explicitly unavailable.
Preserve drafts and unsaved-change protection during navigation. Show save success only after persistence succeeds.

- Associate invalid-field messages with their controls and show the field's invalid state.
- Use shared error toasts for action failures outside a field. Repeated failures from the same action reuse the existing toast.
- Use a toast for a missing location pin; mark the summary pin red while preserving the search field's normal state.
- Use explicit success messages with green icons. A draft selection alone does not justify a save-success message.
- Keep a persistent Empty state when a whole section cannot load. Forecast load errors work without JavaScript and offer a suitable retry or return link.
- If saving fails inside a confirmation dialog, show Retry and Cancel inside that dialog without a duplicate toast.
- Distinguish loading, empty results, unavailable information, and failed requests. An absent forecast does not imply low earthquake activity.

## Do's and Don'ts

- Keep observed facts distinct from uncertain model estimates.
- Use the Backend API for public earthquake and forecast data.
- Preserve keyboard access, visible focus, native links, and reduced-motion support.
- Describe implemented account features accurately without claiming a deployment or delivery provider is ready.
- Preserve the forecast's original 24-hour window and its stated thresholds.
- Avoid exact-earthquake predictions, unsupported geographic claims, and safety claims based on forecast radius.
