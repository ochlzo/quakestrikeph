import { CircleX, MapPin } from "lucide-react";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription, EmptyContent } from "../../../components/ui/empty";
import { Button } from "../../../components/ui/button";
import { Field } from "../../../components/ui/field";
import { Skeleton } from "../../../components/ui/skeleton";
import type { AccountFlowState } from "../useAccountFlow";

export function PreferencesLoading({ flow }: { flow: AccountFlowState; }) {
  const { title } = flow;
  return (
    <div className="account-loading preferences-loading">
      <span className="sr-only" role="status">Loading alert settings</span>
      {title("Alert preferences", "Choose your receive options and the earthquakes you want to hear about.")}
      <form aria-hidden="true">
        {["Email alerts", "SMS alerts"].map((label) => (
          <div className="switch-row" key={label}>
            <span>
              <strong>{label}</strong>
              <Skeleton className="loading-destination" />
            </span>
            <Skeleton className="loading-switch" />
          </div>
        ))}
        <div className="settings-section">
          <div className="field">
            <span className="loading-field-label">Minimum earthquake magnitude</span>
            <Skeleton className="loading-input" />
          </div>
          <p className="support">Choose M1.0 – M10.0. This uses the observed earthquake magnitude.</p>
        </div>
        <div className="nearby-section">
          <div className="switch-row">
            <span>
              <strong>Only earthquakes near my location</strong>
              <small>Apply the same distance rule to both channels.</small>
            </span>
            <Skeleton className="loading-switch" />
          </div>
          <div className="location-summary">
            <MapPin />
            <Skeleton className="loading-location" />
            <Skeleton className="loading-location-action" />
          </div>
        </div>
        <Skeleton className="primary" />
      </form>
    </div>
  );
}

export function AuthLoading({ flow }: { flow: AccountFlowState; }) {
  const { screen } = flow;
  return (
    <div
      className="account-loading"
      role="status"
      aria-label="Loading account"
    >
      <div aria-hidden="true">
        <div className="mode-switch">
          <Skeleton className="loading-tab" />
          <Skeleton className="loading-tab" />
        </div>

        <h2>
          <Skeleton
            className={`loading-heading ${screen === "signup" ? "loading-heading-wide" : ""}`}
          />
        </h2>
        <Skeleton className="form-intro loading-copy" />
        <Skeleton className="google" />
        <div className="divider">
          <Skeleton className="loading-divider" />
        </div>
        <div>
          {(screen === "signup"
            ? ["name", "email", "password"]
            : ["email", "password"]
          ).map((field) => (
            <Field className="field account-form-field" key={field}>
              {field === "password" && screen !== "signup" ? (
                <div className="field-label-row">
                  <Skeleton className="loading-label" />
                  <Skeleton className="loading-forgot" />
                </div>
              ) : (
                <Skeleton className="loading-label loading-label-spaced" />
              )}
              <Skeleton className="loading-input" />
            </Field>
          ))}
          {screen === "signup" && (
            <div className="support loading-password-note">
              <Skeleton />
              <Skeleton />
            </div>
          )}
          <Skeleton className="primary" />
        </div>
        <Skeleton className="mobile-guest loading-guest" />
      </div>
    </div>
  );
}

export function UnavailableAccountScreen({ flow }: { flow: AccountFlowState; }) {
  const { action, resume, busy } = flow;
  return (
    <Empty className="location-empty" role="alert">
      <EmptyHeader>
        <EmptyMedia variant="icon"><CircleX aria-hidden="true" /></EmptyMedia>
        <EmptyTitle>Account settings unavailable</EmptyTitle>
        <EmptyDescription>Your account could not be loaded. You can still read the Bulletin.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent><Button className="secondary" isDisabled={busy} onPress={() => void action(resume)}>
        Try again
      </Button></EmptyContent>
    </Empty>
  );
}
