import { ChevronsUpDown, Eye, EyeOff, LogOut, MapPin, Settings, UserRound } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Menu, MenuItem, MenuTrigger, RouterProvider, Separator } from "react-aria-components";
import { Button } from "../../components/ui/button";
import { Field, FieldError, FieldLabel } from "../../components/ui/field";
import { Input } from "../../components/ui/input";
import { Popover } from "../../components/ui/popover";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from "../../components/ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useIsMobile } from "../../hooks/use-mobile";
import BulletinLayout from "../../components/BulletinLayout";
import AccountHeader from "./AccountHeader";
import type { Screen } from "./routes";
import { screenAtPath } from "./routes";
export const passwordRequirements =
  "Use at least 8 characters, including one lowercase letter, one uppercase letter, and one number.";
export const passwordPattern = "(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9]).{8,}";
function SettingsUserMenu({ name, email, avatarUrl, isLoading, navigate, signOut }: {
  name: string; email?: string; avatarUrl?: string; isLoading: boolean; navigate: (screen: Screen) => void; signOut?: () => void;
}) {
  const { isMobile, setOpenMobile } = useSidebar();
  const identity = (
    <>
      <span className="relative grid size-8 shrink-0 place-items-center overflow-hidden rounded-lg bg-muted" aria-hidden="true">
        {name.slice(0, 1).toUpperCase()}
        {avatarUrl && <img src={avatarUrl} alt="" className="absolute inset-0 size-full object-cover" onError={(event) => { event.currentTarget.hidden = true; }} />}
      </span>
      <span className="grid min-w-0 flex-1 text-left text-sm leading-tight">
        <span className="truncate font-medium">{name || "Loading account…"}</span>
        <span className="truncate text-xs">{email}</span>
      </span>
    </>
  );
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <MenuTrigger>
          <SidebarMenuButton size="lg" className="aria-expanded:bg-sidebar-accent aria-expanded:text-sidebar-accent-foreground" isDisabled={isLoading} aria-label="User menu">
            {identity}<ChevronsUpDown className="ml-auto" aria-hidden="true" />
          </SidebarMenuButton>
          <Popover placement={isMobile ? "bottom end" : "right bottom"} containerPadding={8} className="settings-user-popover">
            <div className="flex items-center gap-2 px-1 py-1.5">{identity}</div>
            <Menu aria-label="User options" className="settings-user-menu">
              <Separator className="settings-user-separator" />
              <MenuItem textValue="Account" onAction={() => { setOpenMobile(false); navigate("account"); }}>
                <UserRound aria-hidden="true" />Account
              </MenuItem>
              <Separator className="settings-user-separator" />
              <MenuItem textValue="Sign-out" onAction={signOut}>
                <LogOut aria-hidden="true" />Sign-out
              </MenuItem>
            </Menu>
          </Popover>
        </MenuTrigger>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
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
  email,
  avatarUrl,
  isLoading = false,
  children,
  navigate,
  signOut,
}: {
  screen: Screen;
  name: string;
  email?: string;
  avatarUrl?: string;
  isLoading?: boolean;
  children: ReactNode;
  navigate: (screen: Screen) => void;
  signOut?: () => void;
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
      if (y <= 56) setHeaderHidden(false);
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
  const settingsRail = (
          <aside className="settings-rail">
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
  );
  const ContentTag = wide ? "div" : "main";
  const content = (
      <ContentTag className="layout">
        {wide && settingsRail}
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
      </ContentTag>
  );
  return (
    <div className={rootClass} data-screen={screen} data-header-hidden={headerHidden || undefined}
      onFocusCapture={(event) => {
        if (event.target.closest(".header, .bulletin-header")) setHeaderHidden(false);
      }}>
      {wide ? (
        <BulletinLayout settings filters={null} results={null}
          sidebarFooter={<SettingsUserMenu name={name} email={email} avatarUrl={avatarUrl} isLoading={isLoading} navigate={navigate} signOut={signOut} />}>
          {content}
        </BulletinLayout>
      ) : (
        <>
          <AccountHeader publicLink={screen === "signin" || screen === "signup" || screen === "forgot"} />
          {content}
          <footer />
        </>
      )}
    </div>
  );
}
