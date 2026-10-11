import { Check, MapPin, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../../../components/ui/button";
import { FieldError } from "../../../components/ui/field";
import { Switch } from "../../../components/ui/switch";
import { toast } from "../../../components/ui/toast";
import { FormField } from "../account-ui";
import { locationLabel } from "../LocationPicker";
import type { AccountFlowState } from "../useAccountFlow";

type PreferencesScreenFlow = Pick<AccountFlowState, "title" | "account" | "draft" | "emailVerified" | "phoneVerified" | "action" | "preferencesNavigation" | "fieldErrors" | "list" | "savePreferences">;

export function PreferencesScreen({ flow }: { flow: PreferencesScreenFlow; }) {
  const {
    title, account,
    draft, emailVerified, phoneVerified,
    action, preferencesNavigation, fieldErrors, list,
    savePreferences,
  } = flow;
  const [magnitudeText, setMagnitudeText] = useState(draft.magnitude.toFixed(1));
  const [magnitudeVersion, setMagnitudeVersion] = useState(0);
  useEffect(() => setMagnitudeText(draft.magnitude.toFixed(1)), [draft.magnitude]);
  const magnitudeChanged = magnitudeText !== draft.magnitude.toFixed(1);
  function discardMagnitude() {
    setMagnitudeText(draft.magnitude.toFixed(1));
    setMagnitudeVersion(version => version + 1);
  }
  return (
    <>
      {title(
        "Alert preferences",
        "Switches save automatically. Use the check to save a magnitude change.",
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (magnitudeChanged) savePreferences({ magnitude: Number(magnitudeText) }, 0);
        }}
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
              onChange={(v) => savePreferences({ emailEnabled: v })}
            />
          ) : (
            <Button
              className="secondary verify-destination"
              aria-label={account?.email ? "Verify email" : "Add email"}
              onPress={() =>
                action(async () => {
                  toast.add({ type: 'info', title: 'Email verification is not available here yet.' });
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
              onChange={(v) => savePreferences({ smsEnabled: v })}
            />
          ) : (
            <Button
              className="secondary verify-destination"
              aria-label={account?.phone ? "Verify mobile number" : "Add number"}
              onPress={() => void preferencesNavigation.openPhone()}
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
            key={magnitudeVersion}
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
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') { event.preventDefault(); discardMagnitude(); }
            }}
            inputAction={magnitudeChanged ? (
              <div className="profile-name-actions magnitude-actions">
                <Button type="submit" variant="link" size="icon" className="profile-name-save" aria-label="Save magnitude">
                  <Check aria-hidden="true" />
                </Button>
                <Button type="button" variant="link" size="icon" className="profile-name-discard" aria-label="Discard magnitude changes" onPress={discardMagnitude}>
                  <X aria-hidden="true" />
                </Button>
              </div>
            ) : undefined}
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
              onChange={(v) => savePreferences({ nearbyOnly: v })}
            />
          </div>
          <div className="location-summary">
            <MapPin />
            <a className="alert-location-link" href="/alerts/location" onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              preferencesNavigation.openLocation();
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
      </form>
    </>
  );
}
