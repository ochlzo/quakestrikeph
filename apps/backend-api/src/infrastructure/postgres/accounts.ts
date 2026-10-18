import { randomUUID } from "node:crypto";
import type { Pool, PoolClient } from "pg";
import {
  AccountError,
  requireActive,
  requireRecent,
  type Account,
  type Identity,
  type Preferences,
} from "../../domain/accounts.js";
import type { AccountStore } from "../../ports/accounts.js";

type Row = Record<string, unknown>;
function account(row: Row): Account {
  const number = (key: string) => (row[key] == null ? null : Number(row[key]));
  return {
    userId: String(row.user_id),
    displayName: String(row.display_name),
    email: String(row.email),
    phone: row.mobile_number == null ? null : String(row.mobile_number),
    status: row.account_status as Account["status"],
    emailEnabled: Boolean(row.email_enabled),
    smsEnabled: Boolean(row.sms_enabled),
    onboardingCompleted: row.onboarding_completed_at != null,
    magnitude: Number(row.alert_trigger_magnitude),
    nearbyOnly: Boolean(row.nearby_alerts_only),
    latitude: number("alert_location_latitude"),
    longitude: number("alert_location_longitude"),
    distanceKm: number("alert_trigger_distance_km"),
  };
}

export class PostgresAccounts implements AccountStore {
  constructor(private pool: Pool) {}
  async failure(
    identity: Identity | undefined,
    code: string,
    requestId: string,
  ) {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ WRITE");
      const user = identity
        ? (
            await client.query(
              "SELECT user_id FROM users WHERE clerk_user_id=$1",
              [identity.clerkUserId],
            )
          ).rows[0]
        : null;
      await client.query(
        `INSERT INTO audit_logs
        (audit_id,actor_type,actor_user_id,action,outcome,reason_code,request_id,correlation_id)
        VALUES ($1,$2,$3,'account_request','denied',$4,$5,$5)`,
        [
          randomUUID(),
          user ? "user" : "anonymous",
          user?.user_id ?? null,
          code,
          requestId,
        ],
      );
      await client.query("COMMIT");
    } catch {
      await client.query("ROLLBACK");
    } finally {
      client.release();
    }
  }

  async read(identity: Identity) {
    const result = await this.pool.query(
      "SELECT * FROM users WHERE clerk_user_id = $1",
      [identity.clerkUserId],
    );
    if (!result.rows[0]) return null;
    this.trusted(result.rows[0], identity);
    return account(result.rows[0]);
  }

  private trusted(row: Row, identity: Identity) {
    requireActive(account(row));
    if (row.email !== identity.email || row.email_verified_at == null) {
      throw new AccountError(
        "EMAIL_MIRROR_MISMATCH",
        "Your account email needs synchronization. Please contact support.",
        409,
      );
    }
  }

  private async transaction(
    identity: Identity,
    action: string,
    requestId: string,
    work: (client: PoolClient, row: Row | undefined) => Promise<Row | null>,
  ) {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN READ WRITE");
      // Serialize profile creation as well as existing-row mutations.
      await client.query(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        [identity.clerkUserId],
      );
      const result = await client.query(
        "SELECT * FROM users WHERE clerk_user_id = $1 FOR UPDATE",
        [identity.clerkUserId],
      );
      if (result.rows[0]) this.trusted(result.rows[0], identity);
      const row = await work(client, result.rows[0]);
      // A null result leaves the locked account unchanged, without a success audit.
      if (row === null) {
        await client.query("COMMIT");
        return account(result.rows[0]);
      }
      await client.query(
        `INSERT INTO audit_logs
        (audit_id, actor_type, actor_user_id, action, target_type, target_id, outcome, request_id, correlation_id, metadata)
        VALUES ($1,'user',$2::uuid,$3,'user',$2::uuid::text,'succeeded',$4,$4,$5)`,
        [
          randomUUID(),
          row.user_id,
          action,
          requestId,
          {
            policyVersion: "bulletin-accounts-v1",
            ...(action === "preferences_saved"
              ? {
                  emailEnabled: row.email_enabled,
                  smsEnabled: row.sms_enabled,
                  nearbyOnly: row.nearby_alerts_only,
                  magnitude: Number(row.alert_trigger_magnitude),
                }
              : {}),
          },
        ],
      );
      await client.query("COMMIT");
      return account(row);
    } catch (error) {
      await client.query("ROLLBACK");
      if (
        error &&
        typeof error === "object" &&
        "code" in error &&
        error.code === "23505"
      ) {
        throw new AccountError(
          "PHONE_UNAVAILABLE",
          "This mobile number cannot be added to this account.",
          409,
          "phone",
        );
      }
      throw error;
    } finally {
      client.release();
    }
  }

  async profile(identity: Identity, name: string, requestId: string) {
    return this.transaction(
      identity,
      "profile_saved",
      requestId,
      async (client, row) => {
        const result = row
          ? await client.query(
              `UPDATE users SET display_name=$2, updated_at=now()
        WHERE user_id=$1 RETURNING *`,
              [row.user_id, name],
            )
          : await client.query(
              `INSERT INTO users
        (user_id, clerk_user_id, display_name, email, email_verified_at) VALUES ($1,$2,$3,$4,now()) RETURNING *`,
              [randomUUID(), identity.clerkUserId, name, identity.email],
            );
        return result.rows[0];
      },
    );
  }

  async save(identity: Identity, p: Preferences, requestId: string) {
    return this.transaction(
      identity,
      "preferences_saved",
      requestId,
      async (client, row) => {
        if (!row)
          throw new AccountError(
            "PROFILE_REQUIRED",
            "Complete your profile first.",
            409,
          );
        if (p.smsEnabled && (!row.mobile_number || !row.mobile_verified_at)) {
          throw new AccountError(
            "PHONE_REQUIRED",
            "Verify a supported mobile number first.",
            400,
            "smsEnabled",
          );
        }
        const result = await client.query(
          `UPDATE users SET email_enabled=$2, sms_enabled=$3,
        alert_trigger_magnitude=$4, nearby_alerts_only=$5, alert_location_latitude=$6,
        alert_location_longitude=$7, alert_trigger_distance_km=$8,
        onboarding_completed_at=COALESCE(onboarding_completed_at,now()), updated_at=now()
        WHERE user_id=$1 RETURNING *`,
          [
            row.user_id,
            p.emailEnabled,
            p.smsEnabled,
            p.magnitude,
            p.nearbyOnly,
            p.latitude,
            p.longitude,
            p.distanceKm,
          ],
        );
        return result.rows[0];
      },
    );
  }

  async pauseSms(identity: Identity, requestId: string) {
    return this.transaction(
      identity,
      "phone_replacement_started",
      requestId,
      async (client, row) => {
        if (!row)
          throw new AccountError(
            "PROFILE_REQUIRED",
            "Complete your profile first.",
            409,
          );
        return (
          await client.query(
            "UPDATE users SET sms_enabled=false, updated_at=now() WHERE user_id=$1 RETURNING *",
            [row.user_id],
          )
        ).rows[0];
      },
    );
  }

  async bindPhone(identity: Identity, phone: string, requestId: string) {
    return this.transaction(
      identity,
      "phone_verified",
      requestId,
      async (client, row) => {
        if (!row)
          throw new AccountError(
            "PROFILE_REQUIRED",
            "Complete your profile first.",
            409,
          );
        if (row.mobile_number) requireRecent(identity);
        return (
          await client.query(
            `UPDATE users SET mobile_number=$2, mobile_verified_at=now(),
        sms_enabled=false, updated_at=now() WHERE user_id=$1 RETURNING *`,
            [row.user_id, phone],
          )
        ).rows[0];
      },
    );
  }

  async phoneAvailable(phone: string, userId: string) {
    return !(
      await this.pool.query(
        "SELECT 1 FROM users WHERE mobile_number=$1 AND user_id<>$2",
        [phone, userId],
      )
    ).rowCount;
  }

  async removePhone(identity: Identity, requestId: string) {
    // The row change and its success audit commit together. Metadata carries no number.
    return this.transaction(
      identity,
      "phone_removed",
      requestId,
      async (client, row) => {
        if (!row)
          throw new AccountError(
            "PROFILE_REQUIRED",
            "Complete your profile first.",
            409,
          );
        if (row.mobile_number === null) return null;
        return (
          await client.query(
            `UPDATE users SET mobile_number=NULL, mobile_verified_at=NULL,
        sms_enabled=false, updated_at=now() WHERE user_id=$1 RETURNING *`,
            [row.user_id],
          )
        ).rows[0];
      },
    );
  }
}
