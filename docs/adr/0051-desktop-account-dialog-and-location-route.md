# Show account settings in a desktop Dialog

**Status**: accepted by the user on 17 October 2026.

Amends ADR 0044's presentation and alert location route. Replace
`/alerts/location` with `/location`, without a compatibility redirect.
`/alerts`, `/location`, `/account`, `/account/phone`, and `/account/password`
share one desktop shadcn Dialog. Preserve the settings navigation and content
layout. Sign-in, account creation, recovery, session tasks, and onboarding
remain full pages.

At 761 CSS pixels and above, the Dialog is at most 1120 pixels wide and 90dvh
high, with at least 24 pixels to each viewport edge. Scroll the content panel
and keep navigation and the corner Close button visible. Below that boundary,
settings fill the mobile viewport. Resizing retains the same mounted settings
flow, including unfinished location edits and verification state.

Direct visits and refreshes also show the desktop Dialog, over the default
Bulletin. Opening settings from the Bulletin retains the public view, including
filters, selection, map camera, and the originating URL. Closing returns to
that view; a direct visit closes to `/`. Public view state remains in memory.
The background cannot receive interaction while the Dialog is open. Focus stays
inside the Dialog and returns to the opening control when available.

The corner X and Escape close the Dialog. Outside clicks do not. Escape first
handles an active menu, nested confirmation, or unsaved magnitude edit. Back
and Forward follow settings navigation. The existing Save changes confirmation
protects unfinished location and display-name edits, including browser Back
and Dialog closure. Failed saves retain the screen and edit. Unsubmitted
magnitude edits keep their existing discard-on-departure behavior.

ADR 0046 still controls background preference saves and notifications after
closing. ADR 0044 still controls authentication, reverification, draft privacy,
refresh behavior, and session isolation. No Backend, database, new dependency,
or router is introduced.

Preload the destination page and its same-origin styles and island modules after
page load, during browser idle time. Skip background downloads on slow
connections or when data-saving mode is enabled. Opening settings retains the
public document shell in memory. Returning to that origin uses Astro's loader
hook instead of a server request, preserving normal history and animations.
Direct settings visits preload the default Bulletin document; if that download
is unavailable or incomplete, closing uses normal navigation.

Cache unhydrated settings documents in tab memory and clone them for subsequent
navigation. Cache each settings destination separately, including its query
string. Never cache the mounted account UI, credentials, drafts, or account API
responses. Reopening mounts a new account flow and performs the usual identity
and account checks. A browser reload clears the document cache. Development
navigation prepares client-only styles before caching its first document;
production can also reuse the preloaded settings document.
