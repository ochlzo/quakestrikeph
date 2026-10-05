import { Eye, EyeOff, MapPin, Settings, UserRound } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { RouterProvider } from "react-aria-components";
import { Button } from "../../components/ui/button";
import { Field, FieldError, FieldLabel } from "../../components/ui/field";
import { Input } from "../../components/ui/input";
import { Skeleton } from "../../components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useIsMobile } from "../../hooks/use-mobile";
import AccountHeader from "./AccountHeader";
import type { Screen } from "./routes";
import { screenAtPath } from "./routes";
export const passwordRequirements =
  "Use at least 8 characters, including one lowercase letter, one uppercase letter, and one number.";
export const passwordPattern = "(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9]).{8,}";
export function FormField({
  id,
  label,
  labelAction,
  error,
  type = "text",
  ...props
}: {
  id: string;
  label: string;
  labelAction?: ReactNode;
  error?: string;
} & React.ComponentProps<typeof Input>) {
  const [visible, setVisible] = useState(false);
  const [validationError, setValidationError] = useState("");
  const fieldError = error || validationError;
  return (
    <Field
      className="field account-form-field"
      data-invalid={fieldError ? true : undefined}
    >
      {labelAction ? (
        <div className="field-label-row">
          <FieldLabel htmlFor={id}>{label}</FieldLabel>
          {labelAction}
        </div>
      ) : (
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
      )}
      <div className={type === "password" ? "password-wrap" : undefined}>
        <Input
          {...props}
          onInvalid={(event) => {
            event.preventDefault();
            props.onInvalid?.(event);
            const input = event.currentTarget;
            setValidationError(
              input.validity.valueMissing
                ? `${label} is required.`
                : input.validity.typeMismatch
                  ? "Enter a valid email address."
                  : type === "password"
                    ? passwordRequirements
                    : input.validationMessage,
            );
            input.form
              ?.querySelector<HTMLInputElement>("input:invalid")
              ?.focus();
          }}
          onChange={(event) => {
            if (event.currentTarget.validity.valid) setValidationError("");
            props.onChange?.(event);
          }}
          id={id}
          type={type === "password" && visible ? "text" : type}
          pattern={
            type === "password" && props.autoComplete === "new-password"
              ? passwordPattern
              : props.pattern
          }
          title={
            type === "password" && props.autoComplete === "new-password"
              ? passwordRequirements
              : props.title
          }
          aria-invalid={!!fieldError}
          aria-describedby={
            fieldError ? `${id}-error` : props["aria-describedby"]
          }
        />
        {type === "password" && (
          <Button
            className="show-password"
            variant="ghost"
            aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
            onPress={() => setVisible((x) => !x)}
          >
            {visible ? <EyeOff /> : <Eye />}
          </Button>
        )}
      </div>
      {fieldError && <FieldError id={`${id}-error`}>{fieldError}</FieldError>}
    </Field>
  );
}
export function Shell({
  screen,
  name,
  isLoading = false,
  children,
  navigate,
}: {
  screen: Screen;
  name: string;
  isLoading?: boolean;
  children: ReactNode;
  navigate: (screen: Screen) => void;
}) {
  const wide = ["preferences", "location", "account"].includes(screen);
  const isMobile = useIsMobile();
  const [headerHidden, setHeaderHidden] = useState(false);
  useEffect(() => {
    setHeaderHidden(false);
    if (!wide || !isMobile) return;
    let previousY = window.scrollY;
    function onScroll() {
      const y = Math.max(0, Math.min(window.scrollY, document.documentElement.scrollHeight - window.innerHeight));
      if (y <= 78) setHeaderHidden(false);
      else if (Math.abs(y - previousY) < 8) return;
      else setHeaderHidden(y > previousY);
      previousY = y;
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [wide, isMobile]);
  const entry = [
    "signin",
    "signup",
    "verify-email",
    "forgot",
    "recovery-code",
    "reset",
    "device-code",
  ].includes(screen);
  const rootClass = `account-app map flow-screen ${wide ? "settings-workspace wide" : entry ? "account-entry" : "focused-shell"}`;
  return (
    <div className={rootClass} data-screen={screen} data-header-hidden={headerHidden || undefined}
      onFocusCapture={(event) => {
        if (event.target.closest(".header")) setHeaderHidden(false);
      }}>
      <AccountHeader
        publicLink={
          screen === "signin" || screen === "signup" || screen === "forgot"
        }
      />
      <main className="layout">
        {wide && (
          <aside className="settings-rail">
            <div className="rail-identity">
              {isLoading ? <Skeleton className="loading-avatar" aria-hidden="true" /> : <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>}
              <div>
                {isLoading ? <Skeleton className="loading-name" aria-hidden="true" /> : <strong>{name}</strong>}
              </div>
            </div>
            <RouterProvider navigate={(path) => {
              const next = screenAtPath(path);
              if (next) navigate(next);
            }}>
              <Tabs className="settings-mobile-tabs" selectedKey={screen} keyboardActivation="manual" isDisabled={isLoading}>
                <TabsList aria-label="Settings">
                  <TabsTrigger id="preferences" href="/alerts"><Settings aria-hidden="true" /><span>Alert preferences</span></TabsTrigger>
                  <TabsTrigger id="location" href="/alerts/location"><MapPin aria-hidden="true" /><span>Alert location</span></TabsTrigger>
                  <TabsTrigger id="account" href="/account"><UserRound aria-hidden="true" /><span>Account</span></TabsTrigger>
                </TabsList>
              </Tabs>
            </RouterProvider>
            <nav className="settings-desktop-nav" aria-label="Settings">
              <Button
                isDisabled={isLoading}
                aria-current={screen === "preferences" ? "page" : undefined}
                onPress={() => navigate("preferences")}
              >
                <Settings />
                Alert preferences
              </Button>
              <Button
                isDisabled={isLoading}
                aria-current={screen === "location" ? "page" : undefined}
                onPress={() => navigate("location")}
              >
                <MapPin />
                Alert location
              </Button>
              <Button
                isDisabled={isLoading}
                aria-current={screen === "account" ? "page" : undefined}
                onPress={() => navigate("account")}
              >
                <UserRound />
                Account
              </Button>
            </nav>
          </aside>
        )}
        <section className="story" aria-labelledby="story-title">
          <div className="story-copy">
            <h1 id="story-title">Earthquake alert settings</h1>
            <p>
              An account is required to save and manage your earthquake alert
              settings.
            </p>
          </div>
          <figure className="map-art">
            <img
              src="/assets/accounts/philippines-offset-map-transparent.png"
              alt=""
              fetchPriority="high"
            />
          </figure>
          <p className="story-note">
            The public Bulletin is available without an account.
          </p>
        </section>
        <section
          className="account"
          aria-labelledby={isLoading ? undefined : "form-title"}
          aria-label={isLoading ? "Account" : undefined}
        >
          <div
            className="account-inner"
            key={
              screen === "signin" || screen === "signup" ? "auth" : "account"
            }
          >
            {children}
          </div>
        </section>
      </main>
      <footer />
    </div>
  );
}
