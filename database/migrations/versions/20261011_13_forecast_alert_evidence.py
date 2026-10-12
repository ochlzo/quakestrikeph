"""Approved forecast content, recipients, attempts, and narrow callback evidence."""

# ruff: noqa: E501

from alembic import op

revision = "20261011_13"
down_revision = "20261004_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
CREATE TYPE public.alert_recipient_status AS ENUM
 ('pending','sending','retry_wait','accepted','delivered','failed','unknown','skipped','expired');
CREATE TYPE public.alert_delivery_status AS ENUM ('sending','accepted','delivered','failed','unknown');
ALTER TABLE public.alert_jobs
 ADD COLUMN email_subject_snapshot text,
 ADD COLUMN email_body_snapshot text,
 ADD COLUMN nearby_message_snapshot text,
 ADD COLUMN nearby_email_subject_snapshot text,
 ADD COLUMN nearby_email_body_snapshot text,
 ADD COLUMN content_provenance_snapshot jsonb,
 ADD CONSTRAINT ck_alert_jobs_email_pair CHECK
 ((email_subject_snapshot IS NULL) = (email_body_snapshot IS NULL)),
 ADD CONSTRAINT ck_alert_jobs_forecast_content_group CHECK
 ((content_provenance_snapshot IS NULL AND nearby_message_snapshot IS NULL
   AND nearby_email_subject_snapshot IS NULL AND nearby_email_body_snapshot IS NULL
   AND email_subject_snapshot IS NULL AND email_body_snapshot IS NULL)
  OR (content_provenance_snapshot IS NOT NULL AND nearby_message_snapshot IS NOT NULL
   AND nearby_email_subject_snapshot IS NOT NULL AND nearby_email_body_snapshot IS NOT NULL
   AND email_subject_snapshot IS NOT NULL AND email_body_snapshot IS NOT NULL)),
 ADD CONSTRAINT ck_alert_jobs_new_content_nonblank CHECK
 ((email_subject_snapshot IS NULL OR (email_subject_snapshot = btrim(email_subject_snapshot) AND email_subject_snapshot <> ''))
  AND (email_body_snapshot IS NULL OR (email_body_snapshot = btrim(email_body_snapshot) AND email_body_snapshot <> ''))
  AND (nearby_message_snapshot IS NULL OR (nearby_message_snapshot = btrim(nearby_message_snapshot) AND nearby_message_snapshot <> ''))
  AND (nearby_email_subject_snapshot IS NULL OR (nearby_email_subject_snapshot = btrim(nearby_email_subject_snapshot) AND nearby_email_subject_snapshot <> ''))
  AND (nearby_email_body_snapshot IS NULL OR (nearby_email_body_snapshot = btrim(nearby_email_body_snapshot) AND nearby_email_body_snapshot <> ''))),
 ADD CONSTRAINT ck_alert_jobs_content_provenance_object CHECK
 (content_provenance_snapshot IS NULL OR jsonb_typeof(content_provenance_snapshot) = 'object');
CREATE OR REPLACE FUNCTION public.enforce_alert_assignment_and_snapshots_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.forecast_id, NEW.message_snapshot, NEW.recipient_policy_snapshot,
        NEW.email_subject_snapshot, NEW.email_body_snapshot, NEW.nearby_message_snapshot,
        NEW.nearby_email_subject_snapshot, NEW.nearby_email_body_snapshot,
        NEW.content_provenance_snapshot)
    IS DISTINCT FROM
    ROW(OLD.forecast_id, OLD.message_snapshot, OLD.recipient_policy_snapshot,
        OLD.email_subject_snapshot, OLD.email_body_snapshot, OLD.nearby_message_snapshot,
        OLD.nearby_email_subject_snapshot, OLD.nearby_email_body_snapshot,
        OLD.content_provenance_snapshot) THEN
  RAISE EXCEPTION 'Alert forecast assignment and snapshots are immutable.' USING ERRCODE = 'check_violation';
 END IF;
 RETURN NEW;
END; $$;
DROP TRIGGER trg_alert_jobs_assignment_and_snapshots_immutable ON public.alert_jobs;
CREATE TRIGGER trg_alert_jobs_assignment_and_snapshots_immutable
BEFORE UPDATE OF forecast_id, message_snapshot, recipient_policy_snapshot,
 email_subject_snapshot, email_body_snapshot, nearby_message_snapshot,
 nearby_email_subject_snapshot, nearby_email_body_snapshot, content_provenance_snapshot
ON public.alert_jobs FOR EACH ROW
EXECUTE FUNCTION public.enforce_alert_assignment_and_snapshots_immutable();

CREATE TABLE public.alert_recipients (
 recipient_id uuid PRIMARY KEY,
 alert_job_id uuid NOT NULL,
 user_id uuid,
 channel text NOT NULL,
 destination_snapshot text NOT NULL,
 eligibility_snapshot jsonb NOT NULL,
 resolved_at timestamptz NOT NULL DEFAULT now(),
 delivery_idempotency_key text NOT NULL UNIQUE,
 status public.alert_recipient_status NOT NULL DEFAULT 'pending',
 next_attempt_at timestamptz,
 delivered_at timestamptz,
 last_error_code text,
 processing_lease_expires_at timestamptz,
 worker_execution_id uuid,
 CONSTRAINT fk_alert_recipients_job FOREIGN KEY (alert_job_id)
  REFERENCES public.alert_jobs(alert_job_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CONSTRAINT fk_alert_recipients_user FOREIGN KEY (user_id)
  REFERENCES public.users(user_id) ON UPDATE RESTRICT ON DELETE SET NULL,
 CONSTRAINT uq_alert_recipients_job_channel_destination UNIQUE (alert_job_id, channel, destination_snapshot),
 CONSTRAINT ck_alert_recipients_channel CHECK (channel IN ('email','sms')),
 CONSTRAINT ck_alert_recipients_destination CHECK
 (destination_snapshot = btrim(destination_snapshot) AND destination_snapshot <> ''
  AND (channel <> 'sms' OR destination_snapshot ~ '^\+639[0-9]{9}$')),
 CONSTRAINT ck_alert_recipients_key CHECK
 (delivery_idempotency_key = btrim(delivery_idempotency_key) AND delivery_idempotency_key <> ''),
 CONSTRAINT ck_alert_recipients_eligibility_object CHECK (jsonb_typeof(eligibility_snapshot) = 'object'),
 CONSTRAINT ck_alert_recipients_sending_claim CHECK
 ((status = 'sending' AND processing_lease_expires_at IS NOT NULL AND worker_execution_id IS NOT NULL)
  OR (status <> 'sending' AND processing_lease_expires_at IS NULL AND worker_execution_id IS NULL)),
 CONSTRAINT ck_alert_recipients_retry CHECK ((status = 'retry_wait') = (next_attempt_at IS NOT NULL)),
 CONSTRAINT ck_alert_recipients_delivered CHECK ((status = 'delivered') = (delivered_at IS NOT NULL)),
 CONSTRAINT ck_alert_recipients_error CHECK
 (last_error_code IS NULL OR (last_error_code = btrim(last_error_code) AND length(last_error_code) BETWEEN 1 AND 100))
);
CREATE UNIQUE INDEX uq_alert_recipients_job_user_channel
 ON public.alert_recipients(alert_job_id,user_id,channel) WHERE user_id IS NOT NULL;
CREATE INDEX ix_alert_recipients_user ON public.alert_recipients(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX ix_alert_recipients_job_status ON public.alert_recipients(alert_job_id,status);
CREATE INDEX ix_alert_recipients_retry ON public.alert_recipients(next_attempt_at) WHERE status = 'retry_wait';
CREATE INDEX ix_alert_recipients_sending_lease
 ON public.alert_recipients(processing_lease_expires_at) WHERE status = 'sending';

CREATE TABLE public.alert_delivery_attempts (
 delivery_attempt_id uuid PRIMARY KEY,
 recipient_id uuid NOT NULL,
 attempt_number integer NOT NULL,
 provider text NOT NULL,
 provider_message_id text,
 status public.alert_delivery_status NOT NULL DEFAULT 'sending',
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 provider_status_at timestamptz,
 error_code text,
 error_message text,
 correlation_id uuid NOT NULL,
 content_variant text NOT NULL,
 eligibility_snapshot jsonb NOT NULL,
 provider_evidence_snapshot jsonb,
 CONSTRAINT fk_alert_delivery_attempts_recipient FOREIGN KEY (recipient_id)
  REFERENCES public.alert_recipients(recipient_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
 CONSTRAINT uq_alert_delivery_attempts_recipient_number UNIQUE (recipient_id,attempt_number),
 CONSTRAINT ck_alert_delivery_attempts_number CHECK (attempt_number >= 1),
 CONSTRAINT ck_alert_delivery_attempts_provider CHECK (provider IN ('iprog','brevo')),
 CONSTRAINT ck_alert_delivery_attempts_reference CHECK
 (provider_message_id IS NULL OR (provider_message_id = btrim(provider_message_id) AND length(provider_message_id) BETWEEN 1 AND 512)),
 CONSTRAINT ck_alert_delivery_attempts_closure CHECK ((status = 'sending') = (finished_at IS NULL)),
 CONSTRAINT ck_alert_delivery_attempts_finish_order CHECK (finished_at IS NULL OR finished_at >= started_at),
 CONSTRAINT ck_alert_delivery_attempts_variant CHECK (content_variant IN ('general','nearby')),
 CONSTRAINT ck_alert_delivery_attempts_eligibility_object CHECK (jsonb_typeof(eligibility_snapshot) = 'object'),
 CONSTRAINT ck_alert_delivery_attempts_provider_evidence_object CHECK
 (provider_evidence_snapshot IS NULL OR jsonb_typeof(provider_evidence_snapshot) = 'object'),
 CONSTRAINT ck_alert_delivery_attempts_errors CHECK
 ((error_code IS NULL OR (error_code = btrim(error_code) AND length(error_code) BETWEEN 1 AND 100))
  AND (error_message IS NULL OR (error_message = btrim(error_message) AND length(error_message) BETWEEN 1 AND 500)))
);
CREATE UNIQUE INDEX uq_alert_delivery_attempts_one_sending
 ON public.alert_delivery_attempts(recipient_id) WHERE status = 'sending';
CREATE INDEX ix_alert_delivery_attempts_provider_reference
 ON public.alert_delivery_attempts(provider,provider_message_id) WHERE provider_message_id IS NOT NULL;
CREATE INDEX ix_alert_delivery_attempts_reconcile
 ON public.alert_delivery_attempts(provider,status,provider_status_at,started_at)
 WHERE status IN ('accepted','unknown');

CREATE FUNCTION public.enforce_alert_recipient_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'INSERT' THEN
  IF NEW.user_id IS NULL THEN RAISE EXCEPTION 'Resolution requires an account.' USING ERRCODE = 'check_violation'; END IF;
 ELSE
  IF ROW(NEW.recipient_id,NEW.alert_job_id,NEW.channel,NEW.destination_snapshot,
         NEW.eligibility_snapshot,NEW.resolved_at,NEW.delivery_idempotency_key)
     IS DISTINCT FROM
     ROW(OLD.recipient_id,OLD.alert_job_id,OLD.channel,OLD.destination_snapshot,
         OLD.eligibility_snapshot,OLD.resolved_at,OLD.delivery_idempotency_key)
     OR (NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL) THEN
   RAISE EXCEPTION 'Recipient selection evidence is immutable.' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status = 'delivered' AND NEW.status <> 'delivered' THEN
   RAISE EXCEPTION 'Delivered recipient cannot regress.' USING ERRCODE = 'check_violation';
  END IF;
 END IF;
 IF NEW.status = 'sending' AND NEW.user_id IS NULL THEN
  RAISE EXCEPTION 'Detached recipient cannot send.' USING ERRCODE = 'check_violation';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER trg_alert_recipients_evidence BEFORE INSERT OR UPDATE ON public.alert_recipients
 FOR EACH ROW EXECUTE FUNCTION public.enforce_alert_recipient_evidence();
CREATE FUNCTION public.enforce_alert_attempt_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE recipient_channel text;
BEGIN
 IF TG_OP = 'UPDATE' THEN
  IF ROW(NEW.delivery_attempt_id,NEW.recipient_id,NEW.attempt_number,NEW.provider,
         NEW.started_at,NEW.correlation_id,NEW.content_variant,NEW.eligibility_snapshot)
     IS DISTINCT FROM
     ROW(OLD.delivery_attempt_id,OLD.recipient_id,OLD.attempt_number,OLD.provider,
         OLD.started_at,OLD.correlation_id,OLD.content_variant,OLD.eligibility_snapshot)
     OR (OLD.provider_message_id IS NOT NULL AND NEW.provider_message_id IS DISTINCT FROM OLD.provider_message_id) THEN
   RAISE EXCEPTION 'Attempt identity and send evidence are immutable.' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status = 'delivered' AND NEW.status <> 'delivered' THEN
   RAISE EXCEPTION 'Delivered attempt cannot regress.' USING ERRCODE = 'check_violation';
  END IF;
 END IF;
 SELECT channel INTO recipient_channel FROM public.alert_recipients WHERE recipient_id = NEW.recipient_id;
 IF (recipient_channel = 'email' AND NEW.provider <> 'brevo')
    OR (recipient_channel = 'sms' AND NEW.provider <> 'iprog') THEN
  RAISE EXCEPTION 'Provider must match recipient channel.' USING ERRCODE = 'check_violation';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER trg_alert_delivery_attempts_evidence BEFORE INSERT OR UPDATE ON public.alert_delivery_attempts
 FOR EACH ROW EXECUTE FUNCTION public.enforce_alert_attempt_evidence();

-- Narrow callback capability. HTTP authentication and provider-tag parsing remain Backend responsibilities.
-- Attempt UUID must come from an authenticated provider-returned caller tag, never from destination matching.
CREATE FUNCTION public.quakestrike_reconcile_brevo_delivery(
 p_attempt_id uuid, p_provider_message_id text, p_status text,
 p_provider_status_at timestamptz, p_error_code text DEFAULT NULL)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE a public.alert_delivery_attempts%ROWTYPE; candidate_id uuid; candidate_count integer;
        r public.alert_recipients%ROWTYPE;
BEGIN
 IF p_provider_status_at IS NULL
    OR p_status IS NULL OR p_status NOT IN ('accepted','delivered','failed')
    OR p_provider_message_id IS NULL OR p_provider_message_id <> btrim(p_provider_message_id)
    OR length(p_provider_message_id) NOT BETWEEN 1 AND 512
    OR (p_error_code IS NOT NULL AND (p_error_code <> btrim(p_error_code) OR length(p_error_code) NOT BETWEEN 1 AND 100)) THEN
  RAISE EXCEPTION 'Invalid normalized callback.' USING ERRCODE = '22023';
 END IF;
 candidate_id := p_attempt_id;
 IF candidate_id IS NULL THEN
  SELECT count(*), (array_agg(delivery_attempt_id))[1] INTO candidate_count, candidate_id
   FROM public.alert_delivery_attempts
   WHERE provider = 'brevo' AND provider_message_id = p_provider_message_id;
  IF candidate_count <> 1 THEN RETURN 'uncorrelated'; END IF;
 END IF;
 SELECT * INTO a FROM public.alert_delivery_attempts WHERE delivery_attempt_id = candidate_id;
 IF NOT FOUND OR a.provider <> 'brevo' THEN RETURN 'uncorrelated'; END IF;
 -- All lifecycle writers lock recipient before attempt.
 SELECT * INTO r FROM public.alert_recipients WHERE recipient_id = a.recipient_id FOR UPDATE;
 SELECT * INTO a FROM public.alert_delivery_attempts WHERE delivery_attempt_id = candidate_id FOR UPDATE;
 IF r.channel <> 'email' OR (a.provider_message_id IS NOT NULL AND a.provider_message_id <> p_provider_message_id)
 THEN RETURN 'conflict'; END IF;
 IF a.status = 'delivered'
    OR (a.provider_status_at IS NOT NULL AND p_provider_status_at < a.provider_status_at)
    OR (a.provider_status_at = p_provider_status_at
        AND (CASE p_status WHEN 'delivered' THEN 3 WHEN 'failed' THEN 2 ELSE 1 END)
         <= (CASE a.status WHEN 'delivered' THEN 3 WHEN 'failed' THEN 2 WHEN 'accepted' THEN 1 ELSE 0 END)) THEN RETURN 'ignored'; END IF;
 -- A verified late acceptance must not reopen a terminal failure; delivery proof may correct a prior failure.
 IF a.status = 'failed' AND p_status = 'accepted' THEN RETURN 'ignored'; END IF;
 UPDATE public.alert_delivery_attempts SET
  provider_message_id = p_provider_message_id, status = p_status::public.alert_delivery_status,
  finished_at = coalesce(finished_at,greatest(clock_timestamp(),started_at)),
  provider_status_at = p_provider_status_at,
  error_code = CASE WHEN p_status = 'failed' THEN coalesce(p_error_code,'provider_rejected') ELSE NULL END,
  error_message = NULL
 WHERE delivery_attempt_id = a.delivery_attempt_id;
 -- Only the newest attempt changes a non-delivered summary; delivery proof always wins.
 IF r.status <> 'delivered' AND (p_status = 'delivered' OR NOT EXISTS
    (SELECT 1 FROM public.alert_delivery_attempts WHERE recipient_id = a.recipient_id AND attempt_number > a.attempt_number)) THEN
  UPDATE public.alert_recipients SET status = p_status::public.alert_recipient_status,
   delivered_at = CASE WHEN p_status = 'delivered' THEN p_provider_status_at ELSE NULL END,
   last_error_code = CASE WHEN p_status = 'failed' THEN coalesce(p_error_code,'provider_rejected') ELSE NULL END,
   next_attempt_at = NULL, processing_lease_expires_at = NULL, worker_execution_id = NULL
  WHERE recipient_id = a.recipient_id;
 END IF;
 RETURN 'applied';
END; $$;
REVOKE ALL ON FUNCTION public.quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.enforce_alert_recipient_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.enforce_alert_attempt_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.enforce_alert_assignment_and_snapshots_immutable() FROM PUBLIC;
""")


def downgrade() -> None:
    # Delivery evidence and content must be retained until an explicit destructive rollback decision.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM alert_delivery_attempts)
         OR EXISTS (SELECT 1 FROM alert_recipients)
         OR EXISTS (SELECT 1 FROM alert_jobs WHERE content_provenance_snapshot IS NOT NULL) THEN
        RAISE EXCEPTION 'Retained forecast-alert evidence prevents destructive downgrade.';
      END IF;
    END $$;
    DROP FUNCTION public.quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text);
    DROP TABLE public.alert_delivery_attempts;
    DROP TABLE public.alert_recipients;
    DROP FUNCTION public.enforce_alert_attempt_evidence();
    DROP FUNCTION public.enforce_alert_recipient_evidence();
    DROP TYPE public.alert_delivery_status;
    DROP TYPE public.alert_recipient_status;
    DROP TRIGGER trg_alert_jobs_assignment_and_snapshots_immutable ON public.alert_jobs;
    ALTER TABLE public.alert_jobs
      DROP COLUMN email_subject_snapshot,
      DROP COLUMN email_body_snapshot,
      DROP COLUMN nearby_message_snapshot,
      DROP COLUMN nearby_email_subject_snapshot,
      DROP COLUMN nearby_email_body_snapshot,
      DROP COLUMN content_provenance_snapshot;
    CREATE OR REPLACE FUNCTION public.enforce_alert_assignment_and_snapshots_immutable()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.forecast_id IS DISTINCT FROM OLD.forecast_id
         OR NEW.message_snapshot IS DISTINCT FROM OLD.message_snapshot
         OR NEW.recipient_policy_snapshot IS DISTINCT FROM OLD.recipient_policy_snapshot THEN
        RAISE EXCEPTION 'Alert forecast assignment and snapshots are immutable.'
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER trg_alert_jobs_assignment_and_snapshots_immutable
      BEFORE UPDATE OF forecast_id, message_snapshot, recipient_policy_snapshot ON public.alert_jobs
      FOR EACH ROW EXECUTE FUNCTION public.enforce_alert_assignment_and_snapshots_immutable();
    """)
