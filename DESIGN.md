---
name: QuakeStrike PH Bulletin
description: White and teal interface with pale teal accents for Philippine earthquake information
colors:
  error-red: "#e4201b"
  supporting-charcoal: "color-mix(in srgb, #1a2c30 70%, #ffffff)"
  action-teal: "#0e6873"
  dark-text: "#1a2c30"
  page-canvas: "#fafafa"
  app-border: "#e5e5e5"
  selected-teal-tint: "color-mix(in srgb, #0e6873 10%, #ffffff)"
  action-teal-hover: "color-mix(in srgb, #0e6873 88%, black)"
  map-surface: "#fbfdfd"
  deep-navy: "#0b2c47"
  coastal-teal: "#117e89"
  coastal-teal-deep: "#096975"
  ocean-blue: "#74A9D9"
  cool-canvas: "#f4f7f7"
  white-surface: "#ffffff"
  quiet-border: "#d4e0e3"
  supporting-blue: "#426078"
  selected-aqua: "#e9f7f7"
  event-coral: "#f65a3d"
typography:
  headline:
    fontFamily: "Geist Variable, sans-serif"
    fontSize: "36px"
    fontWeight: 700
    lineHeight: 1.22
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Geist Variable, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Geist Variable, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.2
rounded:
  control: "10px"
  panel: "16px"
spacing:
  tight: "8px"
  standard: "14px"
  loose: "28px"
components:
  button-primary:
    backgroundColor: "{colors.action-teal}"
    textColor: "{colors.white-surface}"
    rounded: "{rounded.control}"
    padding: "0 19px"
    height: "54px"
  button-primary-hover:
    backgroundColor: "{colors.action-teal-hover}"
    textColor: "{colors.white-surface}"
  event-selected:
    backgroundColor: "{colors.selected-teal-tint}"
    textColor: "{colors.dark-text}"
    rounded: "{rounded.control}"
---

# Design System: QuakeStrike PH Bulletin

## Overview

**Creative North Star: "Coastal blue event lens"**

The public Bulletin leads with recent earthquakes and a selected event alongside an interactive Philippine relief map. White surfaces support careful reading; teal marks actions, pale teal accents mark selected events, and lighter charcoal supports secondary text. The map uses OpenFreeMap Liberty's native palette with an ocean-blue (#74A9D9) override and the existing categorical earthquake marker colors. The dense first viewport keeps the observed event facts close to the map without turning forecasts into map zones.

**Key Characteristics:**

- Light mode only in the current implementation.
- Source facts, forecast information, and planned alert enrollment have distinct destinations.
- The map uses geographic tiles and terrain; plotted markers represent observed events.

The theme tokens and Bulletin layout rules share `apps/quakestrikeph-bulletin/src/styles/globals.css`. Map overrides live in its scoped `.map-panel` block; `bulletin.css` is no longer a separate stylesheet.

## Colors

Outside the map, dark text (#1a2c30) sits on white surfaces (#ffffff) and a near-white canvas (#fafafa). Teal (#0e6873) marks actions and navigation; a 10% teal tint supplies selected-card, chip, and menu highlights. A 70% charcoal and 30% white blend carries supporting text, and red (#e4201b) marks errors. The scoped `.map-panel` retains deep navy text, cool canvas, coastal teal controls and forecast metrics, and its original near-white surfaces. Map markers use a slate-to-red categorical scale for observed magnitude, with coral at M5.0–<6.0. The bands follow [PHIVOLCS magnitude terms](https://www.phivolcs.dost.gov.ph/primer-on-the-27-july-2022-magnitude-mw-7-0-northwestern-luzon-earthquake/): minor M3.0–<4.0, light M4.0–<5.0, moderate M5.0–<6.0, and strong or greater M6.0+. Below M3.0 is shown without a PHIVOLCS class name. Pin color encodes magnitude; all pins are the same size. Color does not represent local shaking or damage. Ocean polygons use #74A9D9 in both 2D and 3D. All other basemap colors remain native Liberty values; no custom coastline outline or tinted terrain-shade layer is applied. Supplemental GeoNames labels reuse the native POI text palette.

## Typography

Geist Variable is the page voice outside the map. The scoped map, its controls, legend, and forecast annotation retain Martel Sans with Arial and sans-serif fallbacks. Bold, compact headings identify the current task or event; body text remains plain and readable. Times and magnitudes use tabular-looking numerals where the browser supports them.

Map labels display English letters (A–Z), ñ, Ñ, digits, and spaces only in both 2D and 3D. English names take priority, followed by Latin-script names and the original name. Other accented Latin letters are normalized to ASCII; punctuation and other scripts are removed, and empty labels are hidden. MapLibre's tile protocol creates separate display properties without changing the original names, feature geometry, or basemap styling. The same cleanup applies to supplemental GeoNames labels and road references.

## Layout

At the approved desktop viewport, a 48px-high full-width header and filter strip sit above a left event panel and a larger right map. The event panel is roughly 558px wide at 1585px; the map takes the remaining width. At 760px and below, the map fills the viewport beneath the header and navigation. A bottom-center Show earthquakes button opens the shadcn snap-point drawer at 65% of viewport height; dragging or the expand control reaches full height. The drawer orders location search, a shared row of date and magnitude filters, and the earthquake list without its visible heading or subtitle. Contents scroll inside the drawer with hidden scrollbars and safe-area padding. Escape, outside pressing, a downward swipe, or the close control dismisses it; focus returns to its trigger. Filter and selection state persist between openings and breakpoint changes. Selecting a map marker shows its forecast on the map without scrolling the page. Desktop retains its inline filters and independently scrollable event panel.

The mobile map retains the 24px circular question-mark legend control above attribution. Its compact vertical legend starts open and closes on a second tap, an outside press, map dragging, or Escape. Terrain, zoom, and recenter controls have compact 32px-tall surfaces with extended 44px touch areas. Zoom and recenter share a horizontal toolbar with subtle separators and 44px-wide buttons. The mobile scale has smaller text and a 96px maximum width. Attribution stays closed until clicked.

## Elevation & Depth

Borders and tonal surfaces separate panels. A small, soft shadow lifts floating map controls. The geographic terrain itself provides depth inside the map.

In 3D, MapLibre's native sky renderer fills the space above the horizon with a pale sky and a gentle white horizon blend. Ground fog is disabled to preserve land colors and the chosen ocean blue. No cloud photograph, texture, or DOM overlay is used. The relief placeholder appears only before the live map is ready; the native sky becomes transparent again in 2D.

## Shapes

Panels use 16px corners; fields and selected event cards use 10px corners. Event pins are uniform circles, with an inset navy ring for the selected plot.

## Components

- **Primary action:** solid action teal with white text; deepens with a 12% black mix on hover and retains a visible teal focus outline. Selected event cards use a teal border and pale teal tint; error notices use red text.
- **Filters:** white rounded fields with teal icons, dark labels, and lighter charcoal supporting text. Date uses a select with a custom range calendar. Magnitude uses a searchable shadcn multiselect combobox with the map legend's five bands and colored dots and removable selection chips. Chips stay in one horizontally scrollable row with a hidden scrollbar; the icon and chevron stay fixed. Selection changes smoothly scroll the chip row to keep Add range visible, with instant scrolling when reduced motion is requested. All magnitudes is the first and default option; selecting it deselects the other ranges, and selecting a range deselects All magnitudes. Removing the last range returns to All magnitudes. The default field shows All magnitudes as plain text, replaced by Search ranges when focused. The chevron stays on the right and rotates on focus and blur. Magnitude chips update immediately; results refresh 300 ms after the last selection or removal, including All magnitudes, while the field stays focused. The earthquake list shows skeleton rows during magnitude updates while the heading subtitle stays unchanged; outdated requests are cancelled. The filter and map legend labels are Below M3.0, M3.0 - M3.9, M4.0 - M4.9, M5.0 - M5.9, and Above M6.0. The upper band includes M6.0 and greater.
- **Event list:** one expanded selected card followed by compact selectable rows. Magnitude text in both rows and the selected card uses the same band colors as the map legend. Rows and selected-card headings display the API location description as supplied, removing leading zeroes only from the leading kilometre distance (010 km becomes 10 km). Bearings, municipality names, and all other wording remain intact. No separate Detailed location line is shown. Locations use 14px row text and 16px selected headings; time, depth, and source use at least 12px and wrap on narrow screens. The selected card also shows observed magnitude, Philippine time, depth, source, and a forecast link. Forecast explanations use 12–13px text.
- **Map:** OpenFreeMap Liberty with native labels, clickable event markers, a Mapterhorn terrain toggle, zoom and recenter controls, a magnitude legend, and a scale that updates with zoom. The map starts flat in 2D; the existing starting centers, zoom levels, bounds, selection focus and recenter behavior are retained. 3D permits tilt up to 85° using right-drag, Shift + arrow keys, or two-finger touch pitch, while wheel/pinch and button zoom remain available. A locally served, landmark-only GeoNames snapshot supplements native labels across the Philippines with lower collision priority and nearby-name duplicate suppression; no populated-place or administrative-area supplement is offered. GeoNames CC BY 4.0 attribution accompanies the source. The selected event's Forecast Overview gives the chance of further activity and estimated activity radius matching bold teal headings, each containing its value and followed by an explanation. The circle explanation describes the system’s estimated reach of further activity from the selected earthquake over the 24-hour forecast window. On phones the annotation stays inside the map and scrolls to reveal supporting text.
- **Navigation:** Earthquakes and About use shadcn Tabs with native page links and manual keyboard activation. The tab list uses a neutral surface; the selected tab has a pale teal background and teal text. On desktop, the tabs sit at the horizontal center of the header, with the brand left and Receive alerts right. Receive alerts stays a separate teal action. Mobile tabs fill the navigation row with equal-width triggers, a 36px list, 30px triggers, and 14px Geist Variable at weight 600 (700 for the active item). Only public reading is available without an account; alert setup is labeled as planned.

## Do's and Don'ts

### Do:

- **Do** keep observed event facts distinct from forecast probabilities.
- **Do** use the Backend API as the Bulletin's event-data source.
- **Do** show an explicit selected state in both the list and map.

### Don't:

- **Don't** imply a forecast is an exact prediction or claim an unconfirmed geographic target area.
- **Don't** present planned alert enrollment as working.
- **Don't** add a dark palette until it is selected and designed separately.
