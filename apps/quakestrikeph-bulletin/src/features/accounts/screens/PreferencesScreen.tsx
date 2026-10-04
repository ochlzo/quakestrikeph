import { MapPin } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { FieldError } from "../../../components/ui/field";
import { Switch } from "../../../components/ui/switch";
import { toast } from "../../../components/ui/toast";
import { FormField } from "../account-ui";
import { type Account } from "../api";
import { locationLabel } from "../LocationPicker";
import type { AccountFlowState } from "../useAccountFlow";

export function PreferencesScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    title, form, account, api,
    draft, emailVerified, phoneVerified, updateAccount,
    setDraft, action, setPhone, sensitive,
    navigate, fieldErrors, list, setScreen,
    submit,
  } = flow;
  return (
    <>
      {title(
        "Alert preferences",
        "Choose your receive options and the earthquakes you want to hear about.",
      )}
      <form
        onSubmit={form(async () => {
          const finishing = !account?.onboardingCompleted;
          const next = await api<Account>("/preferences", "PUT", {
            ...draft,
            emailEnabled: emailVerified && draft.emailEnabled,
            smsEnabled: phoneVerified && draft.smsEnabled,
          });
          updateAccount(next);
          if (finishing) setScreen("preferences", true, "/alerts");
          toast.add({ type: "success", title: "Alert preferences saved." });
        })}
      >
        <div className="switch-row">
          <span>
            <strong>Email alerts</strong>
            <small>{account?.email}</small>
          </span>
          {emailVerified ? (
            <Switch
              aria-label="Email alerts"
              isSelected={emailVerified && draft.emailEnabled}
              onChange={(v) => setDraft((p) => ({ ...p, emailEnabled: v }))}
            />
          ) : (
            <Button
              className="secondary verify-destination"
              aria-label="Verify email"
              onPress={() =>
                action(async () => {
                  toast.add({
                    type: "info",
                    title: "Email verification is not available here yet.",
                  });
                })
              }
            >
              Verify
            </Button>
          )}
        </div>
        <div className="switch-row">
          <span>
            <strong>SMS alerts</strong>
            <small>
              {account?.phone ?? "Verify a supported mobile number first."}
            </small>
          </span>
          {phoneVerified ? (
            <Switch
              aria-label="SMS alerts"
              isSelected={phoneVerified && draft.smsEnabled}
              onChange={(v) => setDraft((p) => ({ ...p, smsEnabled: v }))}
            />
          ) : (
            <Button
              className="secondary verify-destination"
              aria-label="Verify mobile number"
              onPress={() =>
                action(async () => {
                  setPhone(account?.phone ?? "");
                  if (phoneVerified) await sensitive("phone");
                  else navigate("phone");
                })
              }
            >
              Verify
            </Button>
          )}
        </div>
        {fieldErrors.smsEnabled && (
          <FieldError>{fieldErrors.smsEnabled}</FieldError>
        )}
        <div className="settings-section">
          <FormField
            id="magnitude"
            label="Minimum earthquake magnitude"
            type="number"
            min={1}
            max={10}
            step={0.1}
            value={String(draft.magnitude)}
            onChange={(e) =>
              setDraft((p) => ({ ...p, magnitude: Number(e.target.value) }))
            }
            required
            error={fieldErrors.magnitude}
          />
          <p className="support">
            Choose M1.0 – M10.0. This uses the observed earthquake magnitude.
          </p>
        </div>
        <div className="nearby-section">
          <div className="switch-row">
            <span>
              <strong>Only earthquakes near my location</strong>
              <small>Apply the same distance rule to both channels.</small>
            </span>
            <Switch
              aria-label="Only earthquakes near my location"
              isSelected={draft.nearbyOnly}
              onChange={(v) => setDraft((p) => ({ ...p, nearbyOnly: v }))}
            />
          </div>
          <div className="location-summary">
            <MapPin />
            <span>
              {locationLabel(draft.latitude, draft.longitude, list)}
              {draft.distanceKm ? ` · Within ${draft.distanceKm} km` : ""}
            </span>
            <Button
              className="text-button"
              variant="link"
              onPress={() => setScreen("location")}
            >
              Choose location
            </Button>
          </div>
          {(fieldErrors.location ||
            fieldErrors.latitude ||
            fieldErrors.distanceKm) && (
              <FieldError>
                {fieldErrors.location ??
                  fieldErrors.latitude ??
                  fieldErrors.distanceKm}
              </FieldError>
            )}
        </div>
        {submit("Save preferences", false)}
      </form>
    </>
  );
}
