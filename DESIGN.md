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

Geist Variable is the page voice throughout the interface, including the map controls, legend, scale, and forecast annotation, with a sans-serif fallback. Geographic labels rendered inside the basemap retain the map provider's native fonts. Bold, compact headings identify the current task or event; body text remains plain and readable. Times and magnitudes use tabular-looking numerals where the browser supports them.

Map labels display English letters (A–Z), ñ, Ñ, digits, and spaces only in both 2D and 3D. English names take priority, followed by Latin-script names and the original name. Other accented Latin letters are normalized to ASCII; punctuation and other scripts are removed, and empty labels are hidden. MapLibre's tile protocol creates separate display properties without changing the original names, feature geometry, or basemap styling. The same cleanup applies to supplemental GeoNames labels and road references.

Label cleanup runs inside MapLibre's existing worker rather than on the UI thread. Cleaned public tiles persist in a versioned browser Cache Storage cache keyed by the provider's snapshot URL. It retains at most 16 tiles, each no larger than 2 MiB (32 MiB of tile bodies), evicting older entries. Storage failures and oversized tiles fall back to normal worker processing; private/no-store/no-cache responses are not persisted. Bump the cache version whenever label rules change. This cache contains no earthquake, forecast, or account data.

The homepage preconnects to OpenFreeMap, preloads Liberty's style and tile metadata, and begins loading the shared MapLibre runtime before React hydration completes. The runtime prewarms MapLibre's worker after configuring its URL. MapPanel reuses that same runtime promise; camera and interaction behavior are unchanged. Transformed tiles return without waiting for cache writes. The cache copies tile bytes before MapLibre transfers the original buffer and stores that copy in the background.

## Layout

At desktop widths above 760px, a shadcn floating sidebar sits beside the header and map within one shared page shell. The visible sidebar uses 31% of the page width inside its 8px outer margins, with a 340px minimum and no maximum. From 761px through 1100px, it uses 36% with a 315px minimum. The floating container adds 8px insets on each side. Its fixed header contains the brand, full-width location search, and a shared row of date and magnitude filters. The earthquake heading stays above independently scrollable results. A 56px header contains a sidebar trigger, centered Earthquakes/About navigation, and the existing session-aware alert action, followed by the map. The offcanvas sidebar hides completely with the standard 200ms linear transition. During that transition, a fixed-width map is anchored at the right edge and clipped by its panel without scaling geography or markers. At the end, the map resizes without moving the visible image, then pans back to its previous center over 220ms at the same zoom level. Other container size changes resize and redraw immediately. The sidebar and map keep rounded boundaries and 8px outer spacing. The header and map have no enclosing card, border, or separate background.

At 760px and below, the 56px header contains a sidebar trigger, centered QuakeStrike PH title, and a quiet bell link. Both icon controls have 44px touch areas. The bell retains the session-aware alert destination and accessible label. The sidebar opens as a left overlay with a dark backdrop, brand, close control, and Earthquakes/alert action/About links. Filters and results remain in the existing bottom drawer. A bottom-center Show earthquakes button opens the shadcn snap-point drawer at 65% of viewport height; dragging or the expand control reaches full height. The drawer orders location search, a shared row of date and magnitude filters, and the earthquake list without its visible heading or subtitle. Contents scroll inside the drawer with hidden scrollbars and safe-area padding. Escape, outside pressing, a downward swipe, or the close control dismisses it; focus returns to its trigger. Filter and selection state persist between openings and breakpoint changes. Selecting a map marker shows its forecast on the map without scrolling the page.

The mobile sidebar matches shadcn sidebar-04 motion: a full-width offscreen slide without fading the drawer, opening over 500ms and closing over 300ms with ease-in-out timing. Reduced motion disables the transition. The bottom drawer retains its separate motion.

The mobile map uses a 24px circular question-mark legend control with a 14px icon and an extended 44px touch area at the bottom right, aligned with the Show earthquakes button above attribution. Its compact vertical legend starts open and closes on a second tap, an outside press, map dragging, or Escape. Terrain, zoom, and recenter controls have compact 32px-tall surfaces with extended 44px touch areas. Zoom and recenter share a horizontal toolbar with subtle separators and 44px-wide buttons. The mobile scale has smaller text and a 96px maximum width. Attribution stays closed until clicked.

The homepage renders the first 30 earthquake rows in its initial HTML using
the public Backend API. A failed or timed-out server request leaves the browser
to restore saved rows or retry. Hydration retains fresh server rows during the
background request, rather than replacing them with an older browser result.
When initial rows are unavailable, the list restores the last successful search from the same browser
tab when its filters match. The cache contains at most 30 public summary rows;
loading more rows does not enlarge it. The first page refreshes in the
background without a saved-results timestamp. Fresh results replace the list and
its pagination cursor; failed refreshes retain the saved rows and report the
failure. Missing, invalid, or unavailable storage falls back to normal loading.
Restoring a page through the browser's back/forward cache also refreshes the
first page. The cache stores no private account data or event detail responses.

### Mobile forms and cards

At 760px and below, prefer fewer visible cards. Simple forms, including profile completion and alert setup, use a white page background beneath the existing header. Remove the outer card's rounded corners and surrounding canvas gaps. Keep comfortable horizontal padding around the form and preserve field borders and button shapes.

Keep short forms near the top, below the header. Do not vertically center them by default. Allow scrolling when content or the open keyboard reduces available space. Empty space below a short form is acceptable.

Apply the white mobile page to every account screen, including authentication, recovery, onboarding, phone verification, identity verification, and password forms. Hide the decorative story/map panel on mobile. Preserve desktop cards and the existing form controls.

Use cards when their boundaries help users distinguish separate groups, selectable options, or independent items. Avoid wrapping an entire mobile task in a card merely to repeat the desktop layout. Desktop may retain its centered card.

## Elevation & Depth

Borders and tonal surfaces separate panels. A small, soft shadow lifts floating map controls. The geographic terrain itself provides depth inside the map.

In 3D, MapLibre's native sky renderer fills the space above the horizon with a pale sky and a gentle white horizon blend. Ground fog is disabled to preserve land colors and the chosen ocean blue. No cloud photograph, texture, or DOM overlay is used. The loading placeholder is a static capture of the current default 2D basemap, with ocean-blue water and cleaned labels, excluding controls and earthquake data. It appears only before the live map is ready; the native sky becomes transparent again in 2D.

## Shapes

Panels use 16px corners; account fields and Bulletin filters use 12px corners, while selected event cards use 10px corners. Event pins are uniform circles, with an inset navy ring for the selected plot.

Bulletin filters match the account fields: 52px height, 14px horizontal padding, 15px text, white surfaces, and a neutral #dce3e4 border. Focus uses a 3px ring at 50% teal opacity. Hover keeps the neutral border and white background. The search stays full width above the shared date and magnitude row on desktop and in the mobile drawer.

## Components

- **Primary action:** solid action teal with white text; deepens with a 12% black mix on hover and retains a visible teal focus outline. Selected event cards use a teal border and pale teal tint. Field errors use red text; other action errors use error toasts.
- **Filters:** white rounded fields with teal icons, dark labels, and lighter charcoal supporting text. Date uses a select with a custom range calendar. Magnitude uses a searchable shadcn multiselect combobox with the map legend's five bands and colored dots and removable selection chips. Chips stay in one horizontally scrollable row with a hidden scrollbar; the icon and chevron stay fixed. Selection changes smoothly scroll the chip row to keep Add range visible, with instant scrolling when reduced motion is requested. All magnitudes is the first and default option; selecting it deselects the other ranges, and selecting a range deselects All magnitudes. Removing the last range returns to All magnitudes. The default field shows All magnitudes as plain text, replaced by Search ranges when focused. The chevron stays on the right and rotates on focus and blur. Magnitude chips update immediately; results refresh 300 ms after the last selection or removal, including All magnitudes, while the field stays focused. The earthquake list shows skeleton rows during magnitude updates while the heading subtitle stays unchanged; outdated requests are cancelled. The filter and map legend labels are Below M3.0, M3.0 - M3.9, M4.0 - M4.9, M5.0 - M5.9, and Above M6.0. The upper band includes M6.0 and greater.
- **Event list:** one expanded selected card followed by compact selectable rows. Magnitude text in both rows and the selected card uses the same band colors as the map legend. Rows and selected-card headings display the API location description as supplied, removing leading zeroes only from the leading kilometre distance (010 km becomes 10 km). Bearings, municipality names, and all other wording remain intact. No separate Detailed location line is shown. Locations use 14px row text and 16px selected headings; time, depth, and source use at least 12px and wrap on narrow screens. The selected card also shows observed magnitude, Philippine time, depth, source, and a forecast link. Forecast explanations use 12–13px text.
- **Map:** OpenFreeMap Liberty with native labels, clickable event markers, a Mapterhorn terrain toggle, zoom and recenter controls, a magnitude legend, and a scale that updates with zoom. The map starts flat in 2D; the existing starting centers, zoom levels, bounds, selection focus and recenter behavior are retained. 3D permits tilt up to 85° using right-drag, Shift + arrow keys, or two-finger touch pitch, while wheel/pinch and button zoom remain available. A locally served, landmark-only GeoNames snapshot supplements native labels across the Philippines with lower collision priority and nearby-name duplicate suppression; no populated-place or administrative-area supplement is offered. GeoNames CC BY 4.0 attribution accompanies the source. The selected event's Forecast Overview gives the chance of further activity and estimated activity radius matching bold teal headings, each containing its value and followed by an explanation. The circle explanation describes the system’s estimated reach of further activity from the selected earthquake over the 24-hour forecast window. The Forecast Overview stays fixed at the top-right of the map below the zoom and recenter controls while the map pans or zooms. It stays inside the map and scrolls to reveal supporting text on shorter screens. A small close button dismisses the overview; clicking elsewhere on the map keeps it open.
- **Navigation:** Earthquakes and About use shadcn Tabs with native page links and manual keyboard activation. The tab list uses a neutral surface; the selected tab has a pale teal background and teal text. On desktop, the tabs sit at the horizontal center of the header, with the brand left and Receive alerts right. Receive alerts stays a separate teal action. Mobile tabs fill the navigation row with equal-width triggers, a 36px list, 30px triggers, and 14px Geist Variable at weight 600 (700 for the active item). Only public reading is available without an account; alert setup is labeled as planned.

### Error and success feedback

The account name starts read-only. An Edit button beside the Name label enables editing. During editing, background-free Lucide Check and X buttons replace Edit. The green Check saves the name; the red X discards the draft and restores the saved name. The form has no separate Save profile button.

These rules record the user's preferred behavior for new screens and related refinements. Existing screens may still need updates.

- Use the shared error toast for an action failure that does not belong to an editable field. Do not append standalone red error text below a form.
- Use shadcn Field error styling for an invalid field value or an unavailable field operation. Place the error beside the affected field and associate it with the control. Show the field's invalid state and color its associated icon red.
- A missing alert-location pin uses an error toast. Color the location-summary pin icon red, but keep the search field in its normal state.
- Error toasts appear at the bottom right on desktop and the upper right on mobile. Use red error icons. Repeated failures from the same action reuse the existing toast.
- Use green icons for every success toast in the shared toast component. Keep the accompanying text explicit about the completed action. Show save success only after the save succeeds; selecting a draft value is not a successful save.
- Keep a dedicated error state when an entire map or section cannot load. Use a minimal shadcn Empty composition with Lucide's CircleX icon instead of standalone error text below the form.
- When a save fails inside an active confirmation dialog, replace the dialog content with the failure title, error message, Retry, and Cancel. Do not add a duplicate error toast.

## Do's and Don'ts

### Do:

- **Do** keep observed event facts distinct from forecast probabilities.
- **Do** use the Backend API as the Bulletin's event-data source.
- **Do** show an explicit selected state in both the list and map.

### Don't:

- **Don't** imply a forecast is an exact prediction or claim an unconfirmed geographic target area.
- **Don't** present planned alert enrollment as working.
- **Don't** add a dark palette until it is selected and designed separately.

The account settings navigation uses the shared shadcn Tabs on mobile (760px and below). Alert preferences, Alert location, and Account retain native page links, their icons, and the selected destination. Arrow keys move focus; Enter opens the focused destination through the existing account navigation to preserve drafts and unsaved-change confirmation. Desktop retains the settings rail.

On mobile settings pages, downward scrolling slides the main header out and moves the sticky tabs to the top. Upward scrolling restores the header and places the tabs below its 56px height. Keyboard focus on a header link also restores the header. Reduced motion disables these transitions.

The three account settings destinations share the Bulletin sidebar controls. Their standard sidebar starts collapsed on desktop and contains Earthquakes, Alert settings, About, and a user footer menu with Account and Sign-out. The desktop settings rail remains beside the form. The full-width header shows Back to Bulletin on desktop and a ChevronLeft link on mobile. Public Bulletin keeps its floating sidebar and header navigation.

The settings user footer follows sidebar-07's NavUser structure: avatar, name, and email in both trigger and dropdown, with dividers before Account and Sign-out. The dropdown opens to the right on desktop and uses mobile placement with collision handling.

On desktop, settings use a 48px icon gutter. Hover or keyboard focus expands the main sidebar over the page. Desktop settings have no sidebar toggles. The user dropdown keeps the sidebar expanded while open. Mobile retains the drawer.
