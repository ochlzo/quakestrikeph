import { MapPin } from "lucide-react";
import { useState } from "react";
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
  const [magnitudeText, setMagnitudeText] = useState(String(draft.magnitude));
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
          setMagnitudeText(next.magnitude.toFixed(1));
          if (finishing) setScreen("preferences", true, "/alerts");
          toast.add({ type: "success", title: "Alert preferences saved." });
        })}
      >
        <div className="switch-row">
          <span>
            <strong>Email alerts</strong>
            <small>{account?.email || "Add an email address first."}</small>
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
              aria-label={account?.email ? "Verify email" : "Add email"}
              onPress={() =>
                action(async () => {
                  toast.add({
                    type: "info",
                    title: "Email verification is not available here yet.",
                  });
                })
              }
            >
              {account?.email ? "Verify" : "Add email"}
            </Button>
          )}
        </div>
        <div className="switch-row">
          <span>
            <strong>SMS alerts</strong>
            <small>
              {account?.phone || "Add a supported mobile number first."}
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
              aria-label={account?.phone ? "Verify mobile number" : "Add number"}
              onPress={() =>
                action(async () => {
                  setPhone(account?.phone ?? "");
                  if (phoneVerified) await sensitive("phone");
                  else navigate("phone");
                })
              }
            >
              {account?.phone ? "Verify" : "Add number"}
            </Button>
          )}
        </div>
        {fieldErrors.smsEnabled && (
          <FieldError>{fieldErrors.smsEnabled}</FieldError>
        )}
        <div className="settings-section">
          <FormField
            id="magnitude"
            label="Alert me for earthquakes of magnitude:"
            inputSuffix="or higher"
            aria-describedby="magnitude-help"
            type="text"
            inputMode="decimal"
            pattern="(?:[1-9](?:\.[0-9])?|10(?:\.0)?)"
            title="Enter a magnitude from 1.0 to 10.0, using at most one decimal place."
            value={magnitudeText}
            onChange={(e) => {
              if (!/^\d*(?:\.\d?)?$/.test(e.target.value)) return;
              setMagnitudeText(e.target.value);
              setDraft((p) => ({ ...p, magnitude: Number(e.target.value) }));
            }}
            required
            error={fieldErrors.magnitude}
          />
          <p id="magnitude-help" className="support">
            Receive alerts only for earthquakes with a reported magnitude of this value or higher.
            Choose a value from 1.0 to 10.0.
          </p>
        </div>
        <div className="nearby-section">
          <div className="switch-row">
            <span>
              <strong>Only earthquakes near my location</strong>
              <small>Receive alerts only for earthquakes within your chosen distance of your saved location.</small>
            </span>
            <Switch
              aria-label="Only earthquakes near my location"
              isSelected={draft.nearbyOnly}
              onChange={(v) => setDraft((p) => ({ ...p, nearbyOnly: v }))}
            />
          </div>
          <div className="location-summary">
            <MapPin />
            <a className="alert-location-link" href="/alerts/location" onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              setScreen("location");
            }}>
              {locationLabel(draft.latitude, draft.longitude, list)}
              {draft.distanceKm ? ` · Within ${draft.distanceKm} km` : ""}
            </a>
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
