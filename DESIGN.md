---
name: QuakeStrike PH Bulletin
description: Coastal blue interface for reading Philippine earthquake information
colors:
  deep-navy: "#0b2c47"
  coastal-teal: "#117e89"
  coastal-teal-deep: "#096975"
  cool-canvas: "#f4f7f7"
  white-surface: "#fbfdfd"
  quiet-border: "#d4e0e3"
  supporting-blue: "#426078"
  selected-aqua: "#e9f7f7"
  map-water: "#a4c6d3"
  event-coral: "#f65a3d"
typography:
  headline:
    fontFamily: "Martel Sans, Arial, sans-serif"
    fontSize: "36px"
    fontWeight: 800
    lineHeight: 1.22
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Martel Sans, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Martel Sans, Arial, sans-serif"
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
    backgroundColor: "{colors.coastal-teal}"
    textColor: "{colors.white-surface}"
    rounded: "{rounded.control}"
    padding: "0 19px"
    height: "54px"
  button-primary-hover:
    backgroundColor: "{colors.coastal-teal-deep}"
    textColor: "{colors.white-surface}"
  event-selected:
    backgroundColor: "{colors.selected-aqua}"
    textColor: "{colors.deep-navy}"
    rounded: "{rounded.control}"
---

# Design System: QuakeStrike PH Bulletin

## Overview

**Creative North Star: "Coastal blue event lens"**

The public Bulletin leads with recent earthquakes and a selected event alongside an interactive Philippine relief map. Calm blue surfaces support careful reading; teal marks actions and selection, while coral marks earthquake plots. The dense first viewport keeps the observed event facts close to the map without turning forecasts into map zones.

**Key Characteristics:**

- Light mode only in the current implementation.
- Source facts, forecast information, and planned alert enrollment have distinct destinations.
- The map uses geographic tiles and terrain; plotted markers represent observed events.

## Colors

Deep navy carries primary text, cool canvas and white surfaces support dense information, and coastal teal marks navigation and actions. Map markers use a slate-to-red categorical scale for observed magnitude, with coral at M5.0–<6.0. The bands follow [PHIVOLCS magnitude terms](https://www.phivolcs.dost.gov.ph/primer-on-the-27-july-2022-magnitude-mw-7-0-northwestern-luzon-earthquake/): minor M3.0–<4.0, light M4.0–<5.0, moderate M5.0–<6.0, and strong or greater M6.0+. Below M3.0 is shown without a PHIVOLCS class name. Pin color encodes magnitude; all pins are the same size. Color does not represent local shaking or damage. `map-water` is the water fill in the live map.

## Typography

Martel Sans is the page voice. Bold, compact headings identify the current task or event; body text remains plain and readable. Times and magnitudes use tabular-looking numerals where the browser supports them.

## Layout

At the approved desktop viewport, a full-width header and filter strip sit above a left event panel and a larger right map. The event panel is roughly 558px wide at 1585px; the map takes the remaining width. Below 900px the interface stacks vertically. At phone width the map precedes the event list, with controls in two rows.

## Elevation & Depth

Borders and tonal surfaces separate panels. A small, soft shadow lifts floating map controls. The geographic terrain itself provides depth inside the map.

## Shapes

Panels use 16px corners; fields and selected event cards use 10px corners. Event pins are uniform circles, with an inset navy ring for the selected plot.

## Components

- **Primary action:** solid coastal teal with white text; deepens on hover and retains a visible focus outline.
- **Filters:** white rounded fields with navy icons and labels. Date uses a select with a custom range calendar. Magnitude uses a searchable shadcn multiselect combobox with the map legend's five bands and colored dots and removable selection chips. All magnitudes is the first and default option; selecting it deselects the other ranges, and selecting a range deselects All magnitudes. Removing the last range returns to All magnitudes. The default field shows All magnitudes as plain text, replaced by Search ranges when focused. The chevron stays on the right and rotates on focus and blur. Magnitude changes apply when focus leaves the field. The filter and map legend labels are Below M3.0, M3.0 - M3.9, M4.0 - M4.9, M5.0 - M5.9, and Above M6.0. The upper band includes M6.0 and greater.
- **Event list:** one expanded selected card followed by compact selectable rows. The selected card shows observed magnitude, Philippine time, location, depth, source, and a forecast link.
- **Map:** live relief tiles, clickable event markers, terrain toggle, zoom and recenter controls, a magnitude legend, and a scale that updates with zoom.
- **Navigation:** Earthquakes, Forecasts, About, and Receive alerts. Only public reading is available without an account; alert setup is labeled as planned.

## Do's and Don'ts

### Do:

- **Do** keep observed event facts distinct from forecast probabilities.
- **Do** use the Backend API as the Bulletin's event-data source.
- **Do** show an explicit selected state in both the list and map.

### Don't:

- **Don't** imply a forecast is an exact prediction or claim an unconfirmed geographic target area.
- **Don't** present planned alert enrollment as working.
- **Don't** add a dark palette until it is selected and designed separately.
