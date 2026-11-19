# Permit manual cleanup of disposable VPS test accounts

**Status**: accepted by the user on 20 October 2026.

The owner may remove explicitly selected disposable test accounts on the VPS, including their audit and delivery evidence.
This is a narrow exception to the retained-account policy, not a product account-removal route or a general retention policy.
Ordinary account ownership, application grants, and schema constraints remain unchanged.

A separate profiled Compose file runs the installed tested worker image with the migration login, account Redis, and Clerk access.
Deployment and ordinary startup never include this file. The operation requires explicit emails, a reviewed preview token, and a matching selection.
Local accounts and dependent counts are rechecked inside the deletion transaction; provider deletion follows the committed database work.
The [manual procedure](../operations/account-cleanup.md) requires backup evidence, a pause for account writes and alert consumers, and maintenance-lock coordination.
PostgreSQL and provider deletion cannot be atomic; failures require inspection rather than automatic restoration or blind retries.
