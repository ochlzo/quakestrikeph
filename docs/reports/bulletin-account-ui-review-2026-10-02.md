# Bulletin account interface review — 2 October 2026

The fresh full Impeccable reviewer disposition is **ship**, within the reviewed interface and isolated browser-fixture scope. The reviewer completed the five-section full review against all twelve refreshed captures and the current passing checks, with no material fixes remaining. That full review supersedes the earlier recapture disposition. This is not certification of live Clerk, IPROG, PostgreSQL, or Redis integrations, and does not authorize deployment.

## Authority and extension boundaries

This is an ordinary extension of the existing Bulletin system and the approved account mockups. The references checked were `PRODUCT.md`, root `DESIGN.md`, `.codex/skills/impeccable/reference/document.md`, `docs/design/auth-landing-variations/README.md`, and the approved `docs/specs/bulletin-accounts-implementation-plan.md`. The implementation inspected was `apps/quakestrikeph-bulletin/src/features/accounts/AccountApp.tsx`, `LocationPicker.tsx`, and `src/styles/accounts.css`, with the imported `account-reference.css` and `account-flow.css` compositions.

The account surfaces preserve Geist Variable, action teal, dark text, the activity mark, rounded white form surfaces, and the approved offset-color Philippine illustration. Desktop entry and recovery retain Map & sheet, including the contained illustration and left explanation card. Mobile retains the compact illustrated header above its form sheet. Setup and sensitive actions use focused forms; settings use a desktop rail and mobile section navigation. These are the approved account-specific compositions, rather than replacements for the Bulletin's event-list/map layout.

The extension uses the existing aria-nova shadcn control vocabulary for buttons, fields, field errors, switches, combobox selection and toast feedback. Application-level loading, verification, failure and saving states extend the formerly inert gallery. Public-reading links remain available. The decorative entry illustration represents no observations or forecast area.

## Evidence checked

The documenter inspected all twelve images below, the current `checks.json`, and the relevant source. Evidence is stored under `apps/quakestrikeph-bulletin/.impeccable/review/accounts/`:

| Screen | Desktop capture | Mobile capture |
| --- | --- | --- |
| Sign-in | `signin-desktop.png` | `signin-mobile.png` |
| Device verification | `device-code-desktop.png` | `device-code-mobile.png` |
| Preferences | `preferences-desktop.png` | `preferences-mobile.png` |
| Location | `location-desktop.png` | `location-mobile.png` |
| Account | `account-desktop.png` | `account-mobile.png` |
| Password | `password-desktop.png` | `password-mobile.png` |

Desktop browser viewports were 1440 × 1000; mobile viewports were 390 × 844. The PNGs include full-page content, so their image height can exceed the viewport. `checks.json` records `status: passed`, twelve evidence entries, no errors, and `providerMode: isolated fixtures; no live provider sends`. This document does not claim additional test coverage from that summary.

Both location captures show loaded, attributed geographic tiles around Davao and an updated 75 km circle. Labels, selection summaries and distance controls are legible; coordinate fields and coordinate readouts are absent. The radius illustrates the user's nearby preference, not a forecast target. The source includes local place search, movable pin, a map-centre pin action, and location requested only through an explicit action. GeoNames attribution and incomplete-place-coverage wording are visible.

## Product truth and interaction contract

Email and SMS have separate, explicit switches. Creating an account, selecting a provisional setup route, or verifying a destination does not enable either channel. Both may remain off. Save preferences is the committing action, and the interface states that automatic earthquake alert delivery is not yet available.

Use this location updates the parent preference draft; Cancel discards picker edits. Coordinates remain internal to that draft and authenticated account contracts. Saving preferences commits the location and shared filtering choices with channel choices. The source provides failure feedback, saved toasts, and an unsaved-change confirmation; fixture screenshots alone do not prove durable database writes.

Email change and account removal lead to static unavailable screens, without a mutation or false success. Password policy copy specifies at least fifteen characters, matching the approved development-provider configuration. This review does not establish that a live provider accepted a password, delivered a code, verified a phone, or completed an identity flow.

## Preserved documentation and limitations

Root `DESIGN.md` was preserved. Root `.impeccable/design.json` was absent in the inspected worktree; its absence was preserved, and no replacement sidecar was created. The documenter changed only this report.

Preexisting documentation drift remains: `PRODUCT.md` still describes account screens as planned, claims no approved identity is documented, and describes the Bulletin as a title-only scaffold. Root `DESIGN.md` also describes alert enrollment as planned. The approved account plan and inspected extension are more current for this surface. These inconsistencies are reported here without refreshing global product or design files.

The fresh ship disposition covers the interface and fixture evidence only. Live provider checks and required isolated database/Redis integration checks need their own execution evidence. Credentials and environment files were neither inspected nor included in this report.
