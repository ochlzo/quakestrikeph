# Automate full application deployment after reviewed main changes

**Status**: accepted by the user on 11 October 2026.

Successful main CI deploys the Backend, Bulletin, workers, and already-enabled alert services together. This amends the separate Backend rollout in ADR 0041 and the repeat-release manual boundary in ADR 0047. Reviewed migrations and existing grants run through an explicit release job after an encrypted backup and isolated restore test pass. Container startup still never performs initialization writes.

Stop Beat, Dispatcher, consumers, reconciliation, and Backend before schema work. Serialize migration and grants with the existing host maintenance lock. Use the migration login for DDL and existing provisioning commands for restricted grants. Restore Backend before reconciliation, alert consumption, and publication. Preserve prediction replica count and whether Beat and both alert services ran. Initial alert activation, secrets, model registration, bootstrap, legacy retirement, and actual provider verification remain explicit operator actions.

Rollback images and checkout only when the database revision remains unchanged. If schema changes or cannot be verified, leave processing and Backend stopped, retain the target checkout, and require repair forward. Never automatically downgrade or restore the live database. Save private image tags atomically only after health and public checks pass; retain protected environment backups and previous images.
