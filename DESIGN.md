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

Header logos use `Logo` from `@quakestrikeph/ui/logo`, implemented in
`packages/ui/logo.tsx` with shared styles in `packages/ui/logo.css`.
The component combines Lucide's Earth icon, a teal tile, the QuakeStrike PH
name, and a subtitle. `<Logo />` defaults to Bulletin;
`<Logo subtitle="Alert testing" />` identifies the private testing tool.
Use `href`, `aria-label`, and `className` for navigation and placement.

When an earthquake has no forecast, the forecast page uses one reading column.
The earthquake summary includes its occurrence time. The status explanation
uses the detail API's public availability and reason codes, with a PHIVOLCS
bulletin link and a reminder that absence of a forecast does not imply low
earthquake activity. Processing includes a reload link. Unknown reasons remain
explicit; the page does not promise future generation or expose worker errors.

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

At 760px and below, the 56px header contains a sidebar trigger, centered QuakeStrike PH title, and a quiet bell link. Both icon controls have 44px touch areas. The bell retains the session-aware alert destination and accessible label. The sidebar opens as a left overlay with a dark backdrop, brand, close control, and Earthquakes/alert action/About links.

The existing bottom drawer shows a compact selected earthquake card with magnitude, Philippine time, location, depth, PHIVOLCS source, and View forecast. The PHIVOLCS source becomes a link when the event detail supplies a valid source URL. The compact drawer height follows its content, including safe-area padding. The upper-right controls reuse the existing expand and close icons. In the selected earthquake view, the expand control opens the original search, filters, and earthquake list without the selected card. The close control dismisses every drawer view directly. The drawer has no bottom section buttons or Back to map action.

Swiping upward from the selected earthquake card reveals Forecast Overview in the same drawer. The Up and Down arrow keys provide the same expansion and collapse when focus is inside the selected earthquake view. Earthquake details and Forecast Overview stop at 65% of viewport height. The earthquake list opens at 65% and retains its full-height snap through dragging or the expand control. The earthquake list orders location search, the shared date and magnitude row, and results without the visible heading or subtitle. Contents scroll inside the drawer with hidden scrollbars and safe-area padding. The non-modal drawer leaves the map undimmed and interactive; the visible map height adjusts above the drawer. During mobile opening, dragging, snapping, and dismissal, the visible map height follows the actual top edge of the drawer. Tracking continues through the exit animation and stops when the drawer is idle. The map redraws each resize frame, then recenters the selected earthquake over 220ms after the viewport settles. An active camera movement keeps control until it ends. Reduced motion follows the drawer without an added transition and centers immediately. Outside pressing does not dismiss the drawer.

When the selected card reaches the 65% height limit, an upward swipe reveals Forecast Overview at the same height. The drawer scrolls the forecast heading into view. A downward swipe restores the card unless the gesture dismisses the drawer.

Selecting a map marker returns the drawer to its compact earthquake card without scrolling the page. Swiping downward from Forecast Overview returns to the compact selected card. Selecting an earthquake in the list also returns to its compact card. After dismissal, the bottom-center Show earthquakes action always opens the search, filters, and earthquake list, including when an earthquake remains selected. Tapping a map marker reopens its compact selected card, including when that marker is already selected. Filter and selection state persist between openings and breakpoint changes.

The mobile earthquake drawer uses 20px horizontal insets and 12px gaps between the magnitude, location, and facts. Depth and source share two equal columns with aligned labels and values. View forecast spans the drawer's content width with a 44px minimum touch target. A 24px gap and a quiet divider separate the earthquake facts from Forecast Overview. The drawer resolves its visible height on the popup before passing that height to its scrolling content, so longer forecasts remain reachable at every snap point.

The mobile sidebar matches shadcn sidebar-04 motion: a full-width offscreen slide without fading the drawer, opening over 500ms and closing over 300ms with ease-in-out timing. Reduced motion disables the transition. The bottom drawer retains its separate motion.

The mobile map uses a 24px circular question-mark legend control with a 14px icon and an extended 44px touch area at the bottom right of the visible map, above attribution. Its compact vertical legend starts open and closes on a second tap, an outside press, map dragging, or Escape. Terrain, zoom, and recenter controls have compact 32px-tall surfaces with extended 44px touch areas. Zoom and recenter share a horizontal toolbar with subtle separators and 44px-wide buttons. The mobile scale has smaller text and a 96px maximum width. Attribution stays closed until clicked.

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
- **Filters:** white rounded fields with dark labels and lighter charcoal supporting text. Date and magnitude fields have no leading icons; their dropdown chevrons remain. Date uses a select with a custom range calendar. Magnitude uses a shadcn Select with multiple selection, the map legend’s five bands, colored dots, and menu selection marks. A single magnitude selection shows its range label; multiple selections show a count such as “3 selected”. Date labels and magnitude summaries stay in one fixed-height row. Custom date labels omit the year when space is limited and retain the complete date in their title. Magnitude summaries scroll horizontally when wider than the field, with hidden scrollbars. The chevrons stay fixed. Both dropdown menus use 36px rows, 14px text, matching insets, and enough width to separate labels from checkmarks. All magnitudes is the first and default option; selecting it deselects the other ranges, and selecting a range deselects All magnitudes. Deselecting the last range returns to All magnitudes. Clicking anywhere inside the field opens the dropdown; the chevron rotates while the dropdown is open. Magnitude labels update immediately; results refresh 300 ms after the last selection or deselection, including All magnitudes, while the dropdown stays open. The earthquake list shows skeleton rows during magnitude updates while the heading subtitle stays unchanged; outdated requests are cancelled. The filter and map legend labels are Below M3.0, M3.0 - M3.9, M4.0 - M4.9, M5.0 - M5.9, and Above M6.0. The upper band includes M6.0 and greater.
- **Event list:** one expanded selected card followed by compact selectable rows. Magnitude text in both rows and the selected card uses the same band colors as the map legend. Rows and selected-card headings display the API location description as supplied, removing leading zeroes only from the leading kilometre distance (010 km becomes 10 km). Bearings, municipality names, and all other wording remain intact. No separate Detailed location line is shown. Locations use 14px row text and 16px selected headings; time, depth, and source use at least 12px and wrap on narrow screens. The selected card also shows observed magnitude, Philippine time, depth, source, and a forecast link. Forecast explanations use 12–13px text.
- **Map:** OpenFreeMap Liberty with native labels, clickable event markers, a Mapterhorn terrain toggle, zoom and recenter controls, a magnitude legend, and a scale that updates with zoom. The map starts flat in 2D; the existing starting centers, zoom levels, bounds, selection focus and recenter behavior are retained. 3D permits tilt up to 85° using right-drag, Shift + arrow keys, or two-finger touch pitch, while wheel/pinch and button zoom remain available. A locally served, landmark-only GeoNames snapshot supplements native labels across the Philippines with lower collision priority and nearby-name duplicate suppression; no populated-place or administrative-area supplement is offered. GeoNames CC BY 4.0 attribution accompanies the source. The selected event's Forecast Overview gives the chance of further activity and estimated activity radius matching bold teal headings, each containing its value and followed by an explanation. The circle explanation describes the system’s estimated reach of further activity from the selected earthquake over the 24-hour forecast window. Above 760px, the Forecast Overview stays fixed at the map's top-right below the zoom and recenter controls while the map pans or zooms. The desktop overview stays inside the map and scrolls to reveal supporting text on shorter screens. A small close button dismisses the desktop overview; clicking elsewhere on the map keeps it open. At 760px and below, swiping upward from the selected earthquake card reveals the same summary inside the existing bottom drawer. The mobile summary uses the drawer's white surface, dark text, teal metrics, and supporting charcoal text; no separate forecast annotation covers the map. The forecast circle remains visible on the map when a valid positive radius is available. On mobile, selecting an earthquake fits the entire activity circle with padding for map controls and attribution. After the drawer settles at a different height, the map fits the circle to the remaining visible area. Small radii retain the existing 7.2 maximum selection zoom; missing or zero radii retain the epicenter focus.
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
- Forecast page load failures use a persistent, server-rendered shadcn Empty composition with Lucide's Earth globe icon. Show the failure reason and a Try again button that reloads the same forecast URL. Invalid or missing earthquake links offer Back to earthquakes instead. The message and action work without JavaScript.
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

The forecast replay ruler stops at Now. The ruler shows no future ticks and clips its forecast band at that boundary. A quiet message beyond Now says “Future observations are not available.” The existing forecast Ends field retains the full 24-hour end time. Wheel, drag, touch, and keyboard navigation cannot scroll past the boundary. Attempts to scroll farther briefly pull the ruler left, then return it over 240 ms; reduced motion removes that movement. Replay seeking stops at Now. Playback pauses exactly at the forecast end when approaching from inside the 24-hour window. The paused control shows the Play icon and remains enabled. Pressing Play at or beyond the forecast end continues toward Now. Manual handle seeking can cross the forecast end without the automatic pause. Playback still stops at Now. Now refreshes during interactions rather than through continuous polling.

The replay always shows two handles, both starting at the forecast start. The lower handle controls the start of the observation range; the upper handle controls its end and advances during playback. The range start stays fixed during playback. When the playback handle approaches a ruler edge, the ruler scrolls over 250ms with ease-out motion to keep the handle visible, including beyond the forecast end. Pausing, seeking, panning, zooming, or resizing cancels that scroll. Reduced motion repositions the ruler immediately. The handles can share a time but cannot cross. Moving the range start backward includes previous earthquakes. Restart returns both handles to the forecast start. Resizing preserves the ruler's visible time. Playback controls use imported Lucide Play, Pause, and RotateCcw icons, with filled Play and Pause icons. An outline speed button beside Restart toggles between 1x and 2x, defaulting to 1x. Its fixed 2.5rem width fits both speed labels, and its 32px height matches the zoom button. Speed changes apply on the next playback step without pausing or seeking. Restart retains the selected speed; entering the forecast page resets speed to 1x. At either speed, playback still pauses exactly at the forecast end and stops at Now.

A left-aligned date label above the replay ruler shows its visible Philippine calendar dates, excluding blank future space after Now. The label updates during pan, zoom, resize, and playback scrolling. A single visible day shows one date; ranges share the month where possible and include years when crossing a year boundary. The label also describes the timeline for screen readers. The replay ruler defaults to the original 24-hour forecast window with 8px on each edge, on desktop and mobile. One shadcn Button sits below the ruler on the right, opposite playback. It uses the outline variant and default text size, with a fixed 5.5rem width across all four views and an invisible 44px touch area. Its four zoom levels show six, 24, 48, and 96 hours. The button labels are “6h view”, “24h view”, “48h view”, and “96h view”. The 24-hour view is the default. Clicking advances the level and wraps level 4 to level 1. Returning to level 2 fits the original forecast window without seeking or pausing playback. Pinch and Ctrl + Scroll select the same four levels around the gesture position; small wheel movements accumulate before changing level. The visible and accessible labels reflect the displayed scale. The accessible label and tooltip also name the next view. Labels become less frequent at wider time scales. Zoom never changes the selected observation range or forecast dates. During an active forecast, the band and ticks still stop at Now; the fitted view leaves the remaining forecast time blank with the existing future-observation message.

Ruler zoom changes use a 250ms ease-out transition for the view button, pinch, and Ctrl + Scroll. The scale settles at exactly six, 24, 48, or 96 hours. Button zoom holds the selected time in place; gesture zoom holds the gesture position. Returning to level 2 also animates the forecast fit. Repeated zoom input starts from the displayed scale. Reduced motion applies the chosen scale immediately.

On the forecast map, the trigger earthquake stays selected. Clicking another observed earthquake centers the map on that pin without changing zoom or enlarging the pin. A small popup shows its magnitude, rounded distance from the trigger epicenter, and occurrence time relative to the trigger earthquake on separate lines. The time difference uses whole minutes below one hour and hours rounded to one decimal otherwise, with before or after wording. Gaps under one minute and matching timestamps have explicit labels. Clicking the map, pressing Escape, closing the popup, or removing that observation from the replay dismisses the popup.

The forecast map's recenter button returns to the trigger epicenter, preserves zoom and terrain orientation, and dismisses any observation popup. The Bulletin map retains its Philippines-wide recenter action.

The forecast facts lead with “Chance of any further activity” and retain the visible magnitude 1.0 threshold. Its percentage uses 40px teal text with a smaller parenthesized likelihood below it, such as “99%” above “(High)”. The percentage and likelihood align to the right. All probability rows place labels on the left, the complete value group on the right, and a chevron in the far-right column. The primary row has extra vertical space. Its bold heading and magnitude threshold form a text stack on the left, centered beside the percentage and likelihood. Columns at 360px or narrower use a 32px primary percentage and 16px likelihood, with tighter gaps, to preserve the side-by-side layout. The heading, threshold, value, and chevron share one clickable area. Group headings align with the row labels. On narrow screens, labels wrap while the percentage and likelihood remain stacked in the same value column. The likelihood uses the existing probability bands: Low below 30%, Moderate from 30% to below 70%, and High from 70%. The magnitude 4.0 and 5.0 probabilities remain smaller rows inside the same group, each labeled “Chance of further activity” with its threshold beneath. A separate “Activity estimates” heading groups the expected count, largest magnitude, and activity radius. All explanations retain their disclosures, and mobile preserves the same reading order.

Forecast facts use one shared left edge for the event title, window, probability labels, activity heading, and expanded explanations. Chevron columns share the right edge. The location sits 8px below the title; group separation uses 24px. An 8px gap above the primary trigger combines with its 20px padding to keep the main probability prominent without excess whitespace. Row subtitles use 4px gaps, and the activity heading uses an 8px bottom gap.

Forecast explanations appear as four consecutive sections: chance, expected count, largest magnitude, and activity radius. Every section stays visible as the reader scrolls. Above 760px, each section pairs its graphic on the left with its explanation on the right. At 760px and below, the graphic sits above the explanation. Headings and quiet horizontal separators distinguish the sections.

The sticky forecast navigation uses shared shadcn Tabs with native section links. A single active highlight slides with the settings tabs’ 320ms easing. Clicking a tab selects its destination immediately and keeps that tab active during automatic scrolling. Another click replaces the destination; manual scroll input resumes tracking the visible section. All content stays visible. Desktop shows Main facts, Forecast details, and Disclaimer. Mobile adds Activity map and uses four equal tabs with 44px touch targets. Arrow keys move focus, Enter follows the section link, and reduced motion disables the sliding transition.

The nested probability chart fits its SVG viewport around the outer visible box with 8px padding. Small and zero probabilities retain readable labels without leaving the diagram at the bottom-right of an oversized frame. The percentage formatting, nested box geometry, colors, and magnitude legend remain unchanged.

### Desktop account Dialog — 17 October 2026

Bulletin's province search and the alert location search share `Search` and
`SearchInput` from `packages/ui/search.tsx`. The component documents the shared
52px height, 14px side padding, 8px icon gap, 20px search icon, typography, border,
corners, and focus ring. Use an accessible input name without adding a visible
label. Set `isLoading` to replace the leading search icon with the shared
Spinner in the same 20px slot. Compose suggestion triggers after the input;
request state, filtering, suggestions, and errors remain owned by each feature.

The province search keeps typed text separate from its applied filter. Fewer
than two trimmed characters leave the applied search, results, map selection,
and pagination unchanged, without a notice or search spinner. Two or more
characters apply the search. Explicit filter-reset actions still clear the
applied query. A direct URL with a one-character query shows the ordinary
earthquake list until a valid search is entered.

At 761 CSS pixels and above, `/alerts`, `/location`, `/account`, and account phone/password steps share one shadcn Dialog. Preserve the settings rail and content layout. The Dialog is at most 1120px wide and 90dvh high, with at least 24px to viewport edges. Scroll the content panel; keep the settings rail and corner X visible. Outside clicks do not dismiss. The public Bulletin stays visible and inactive behind the Dialog, including on direct visits and refreshes. Mobile fills the viewport with the existing tabs and header. One mounted settings tree survives viewport changes. The previous desktop account sidebar and Back to Bulletin header are hidden inside the Dialog. ADR 0051 defines navigation and draft protection.

The alert location editor uses an 8px heading-to-introduction gap, a 16px
search-to-map gap, and 24px before the controls (20px on mobile). A hidden
location summary leaves no extra gap above the distance field. On mobile,
search and device location stack at full width. The map uses a 220-260px
height, zoom buttons have 44px touch targets, and the action row gives the
primary action twice the space of Cancel. Search text uses 16px on mobile.
