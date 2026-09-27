# Use Clerk free email/password and Google authentication for Bulletin accounts

**Status**: accepted

This decision replaces the Google-only sign-in rule and the Google-only recent-login
rule in [ADR 0036](0036-google-accounts-and-independent-phone-verification.md).
The Bulletin remains public without an account. Personal alert settings require a
Clerk session. Clerk owns credentials, email verification, Google OAuth, and
sessions; QuakeStrike never stores a password or password hash. The supported
methods are email/password and Continue with Google. Phone/password,
phone-code, and email-code as a primary sign-in method are outside this
release. A mobile number is an optional alert destination, not a sign-in
identifier. This keeps production identity on
Clerk's free features; IPROG SMS does not authenticate a Clerk session.

An email/password sign-up collects a display name, email, and password. Clerk
must verify the email before the sign-up completes and the user starts alert
setup. A Google sign-up completes Clerk OAuth, then asks for a display name if
needed; it does not request a password or phone. The Backend creates or resumes
the `users` profile for the verified Clerk user ID. An unfinished profile or
alert setup resumes at its first incomplete step on the next sign-in. Public
Bulletin pages remain available throughout.

Show Continue with Google on both sign-in and sign-up. Request Google's account
chooser for that action, while accepting that the provider controls the final
chooser behavior. Do not look up an entered email to redirect a password
attempt to Google or reveal whether it has an account. Password failures use a
generic result and keep Continue with Google available. A Google-first account
has no password by default; adding password sign-in later requires an explicit
account action and recent Clerk reverification. Clerk may link a later Google
login to an existing account when the matching email has been verified. The
stable Clerk user ID keeps the same QuakeStrike profile and preferences; phone
possession never merges accounts. Password reset and recovery use Clerk.

Only the current, Clerk-verified email is eligible as an email alert
destination. The Backend mirrors that address and its verification state in
PostgreSQL and checks current Clerk identity before an account mutation. A
requested email change pauses email alerts until Clerk verifies the new
address and the Backend records it. A phone change requires recent interactive
Clerk reverification, regardless of whether the account originally used Google
or password. The Operations Console remains a separate Cloudflare Access
identity under [ADR 0035](0035-cloudflare-access-operations-console.md).

This is intended design for implementation after the Bulletin application
exists, not a claim that authentication is deployed.

References: [Clerk free-plan features](https://clerk.com/pricing),
[email/password verification flow](https://clerk.com/docs/guides/development/custom-flows/authentication/email-password),
[Google sign-in](https://clerk.com/docs/guides/configure/auth-strategies/social-connections/google),
[Google account-chooser prompt](https://developers.google.com/identity/openid-connect/openid-connect),
and [enumeration protection](https://clerk.com/docs/guides/secure/user-enumeration-protection).
