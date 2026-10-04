import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  AuthenticateWithRedirectCallback,
  ClerkProvider,
  TaskSetupMFA,
  TaskChooseOrganization,
  useAuth,
  useClerk,
  useReverification,
  useSession,
  useUser,
} from "@clerk/react";
import { useSignIn, useSignUp } from "@clerk/react/legacy";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  Loader,
  Mail,
  MapPin,
  Phone,
  Settings,
} from "lucide-react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Skeleton } from "../../components/ui/skeleton";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/ui/tabs";
import { Field, FieldError, FieldLabel } from "../../components/ui/field";
import { Switch } from "../../components/ui/switch";
import { toast, Toaster } from "../../components/ui/toast";
import LocationPicker, { locationLabel, usePlaces } from "./LocationPicker";
import {
  accountRequest,
  AccountFailure,
  type Account,
  type AccountState,
  type PendingPhone,
  type Preferences,
} from "./api";

type Screen =
  | "signin"
  | "signup"
  | "verify-email"
  | "device-code"
  | "forgot"
  | "recovery-code"
  | "reset"
  | "profile"
  | "channels"
  | "phone"
  | "verify-phone"
  | "preferences"
  | "location"
  | "account"
  | "reverify"
  | "password"
  | "change-email"
  | "close";
const preferences = (account: Account): Preferences => ({
  emailEnabled: account.emailEnabled,
  smsEnabled: account.smsEnabled,
  magnitude: account.magnitude,
  nearbyOnly: account.nearbyOnly,
  latitude: account.latitude,
  longitude: account.longitude,
  distanceKm: account.distanceKm,
});
const blank: Preferences = {
  emailEnabled: false,
  smsEnabled: false,
  magnitude: 4.5,
  nearbyOnly: false,
  latitude: null,
  longitude: null,
  distanceKm: null,
};
const passwordRequirements =
  "Use at least 8 characters, including one lowercase letter, one uppercase letter, and one number.";
// Product form validation only; Clerk owns credentials and its server-side rules.
const passwordPattern = "(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9]).{8,}";

function showAuthError(message: string, mode: "signin" | "signup") {
  return toast.add({
    id: "account-auth-error",
    type: "error",
    title:
      mode === "signin"
        ? "Sign-in unsuccessful"
        : "Account creation unsuccessful",
    description: message,
    timeout: 8000,
  });
}

function FormField({
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

function Shell({
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
    <div className={rootClass} data-screen={screen}>
      <header className="header">
        <a className="brand" href="/">
          <span className="brand-mark">
            <Activity />
          </span>
          <span>
            QuakeStrike PH<small>Bulletin</small>
          </span>
        </a>
        <a className="back" href="/">
          <span>
            {screen === "signin" || screen === "signup" || screen === "forgot"
              ? "View Bulletin without an account"
              : "Back to Bulletin"}
          </span>
        </a>
      </header>
      <main className="layout">
        {wide && (
          <aside className="settings-rail">
            <div className="rail-identity">
              <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>
              <div>
                <strong>{name}</strong>
                <small>Personal settings</small>
              </div>
            </div>
            <nav aria-label="Settings">
              <Button
                aria-current={screen === "preferences" ? "page" : undefined}
                onPress={() => navigate("preferences")}
              >
                <Settings />
                Alert preferences
              </Button>
              <Button
                aria-current={screen === "location" ? "page" : undefined}
                onPress={() => navigate("location")}
              >
                <MapPin />
                Alert location
              </Button>
              <Button
                aria-current={screen === "account" ? "page" : undefined}
                onPress={() => navigate("account")}
              >
                <Activity />
                Account
              </Button>
            </nav>
            <p>
              Public earthquake information is available without an account.
            </p>
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

export default function AccountApp({
  publishableKey,
  initial = "alerts",
}: {
  publishableKey: string;
  initial?: string;
}) {
  if (!publishableKey)
    return (
      <Shell screen="signin" name="" navigate={() => {}}>
        <h2 id="form-title">Account access unavailable</h2>
        <p className="form-intro">
          Please try again later. Public earthquake information is still
          available.
        </p>
        <a className="guest" href="/">
          View Bulletin <ArrowRight />
        </a>
      </Shell>
    );
  return (
    <ClerkProvider
      publishableKey={publishableKey}
      signInUrl="/auth?mode=sign-in"
      signUpUrl="/auth?mode=sign-up"
      signInFallbackRedirectUrl="/alerts?entry=1"
      signUpFallbackRedirectUrl="/alerts?entry=1"
      taskUrls={{
        "reset-password": "/alerts",
        "setup-mfa": "/alerts",
        "choose-organization": "/alerts",
      }}
    >
      {initial === "callback" ? (
        <AuthenticateWithRedirectCallback
          signInUrl="/auth?mode=sign-in"
          signUpUrl="/auth?mode=sign-up"
          signInFallbackRedirectUrl="/alerts?entry=1"
          signUpFallbackRedirectUrl="/alerts?entry=1"
        />
      ) : (
        <SessionAccountFlow initial={initial} />
      )}
      <Toaster />
    </ClerkProvider>
  );
}

function SessionAccountFlow({ initial }: { initial: string }) {
  const { isLoaded, isSignedIn, userId, sessionId } = useAuth({
    treatPendingAsSignedOut: false,
  });
  const identity = !isLoaded
    ? "loading"
    : isSignedIn
      ? `${userId}:${sessionId}`
      : "signed-out";
  const [boundary, setBoundary] = useState({ identity, generation: 0 });
  if (boundary.identity !== identity) {
    // Keep the anonymous signup draft at first sign-in. Leaving an authenticated
    // session always discards its private state, even when switching accounts.
    setBoundary({
      identity,
      generation:
        boundary.generation + (boundary.identity === "signed-out" ? 0 : 1),
    });
  }
  return <AccountFlow key={boundary.generation} initial={initial} />;
}

function AccountFlow({ initial }: { initial: string }) {
  const { isLoaded, isSignedIn, getToken } = useAuth({
    treatPendingAsSignedOut: false,
  });
  const { user } = useUser();
  const { session } = useSession();
  const clerk = useClerk();
  const resetTaskPassword = useReverification(async (newPassword: string) => {
    if (!user) throw new Error("Sign in again");
    await user.updatePassword({ newPassword, signOutOfOtherSessions: true });
  });
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();
  const [screen, setScreen] = useState<Screen>(
    initial === "signup" ? "signup" : "signin",
  );
  const [account, setAccount] = useState<Account | null>(null);
  const [pending, setPending] = useState<PendingPhone | null>(null);
  const [draft, setDraft] = useState<Preferences>({ ...blank });
  const [name, setName] = useState(""),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState(""),
    [currentPassword, setCurrentPassword] = useState("");
  const [code, setCode] = useState(""),
    [phone, setPhone] = useState(""),
    [channels, setChannels] = useState<string[]>(["sms"]);
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const [error, setError] = useState(""),
    [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const [returnAction, setReturnAction] = useState<Screen>("phone");
  const [sentAt, setSentAt] = useState(0),
    [now, setNow] = useState(Date.now());
  const [reverifyMethod, setReverifyMethod] = useState<
    "password" | "email_code"
  >("password");
  const heading = useRef<HTMLDivElement>(null),
    signedOnce = useRef(false);
  const { list } = usePlaces();
  const dirty =
    account &&
    (JSON.stringify(draft) !== JSON.stringify(preferences(account)) ||
      (screen === "account" && name !== account.displayName));
  const active = useRef(true);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const previousScreen = useRef(screen);
  useEffect(() => {
    const wasAuth =
      previousScreen.current === "signin" ||
      previousScreen.current === "signup";
    const isAuth = screen === "signin" || screen === "signup";
    if (!(wasAuth && isAuth)) heading.current?.focus();
    previousScreen.current = screen;
    setCode("");
  }, [screen]);
  useEffect(() => {
    if (screen === "signin" || screen === "signup")
      document.title = `${screen === "signup" ? "Create an account" : "Sign in"} · QuakeStrike PH Bulletin`;
  }, [screen]);
  useEffect(() => {
    const restoreAuthMode = () => {
      if (window.location.pathname !== "/auth" || isSignedIn) return;
      setError("");
      setFieldErrors({});
      setPassword("");
      setScreen(
        new URLSearchParams(window.location.search).get("mode") === "sign-up"
          ? "signup"
          : "signin",
      );
    };
    window.addEventListener("popstate", restoreAuthMode);
    return () => window.removeEventListener("popstate", restoreAuthMode);
  }, [isSignedIn]);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const click = (event: MouseEvent) => {
      const anchor = (event.target as Element).closest("a[href]");
      if (
        anchor &&
        !anchor.getAttribute("href")?.startsWith("#") &&
        !window.confirm("Leave without saving your changes?")
      )
        event.preventDefault();
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", click, true);
    };
  }, [dirty]);

  async function api<T>(path = "", method = "GET", body?: unknown) {
    const token = await getToken({ skipCache: true });
    if (!active.current) throw new Error("The account session changed.");
    try {
      return await accountRequest<T>(token, path, method, body);
    } finally {
      // Ignore old successes and errors before state changes or reverification.
      if (!active.current) throw new Error("The account session changed.");
    }
  }
  function updateAccount(next: Account) {
    setAccount(next);
    setDraft(preferences(next));
    setName(next.displayName);
  }
  async function resume() {
    const state = await api<AccountState>();
    if (state.account) updateAccount(state.account);
    setPending(state.pending);
    if (state.nextStep === "complete") {
      if (
        ["signin", "signup"].includes(initial) ||
        new URLSearchParams(location.search).has("entry")
      ) {
        location.assign("/");
        return;
      }
      setScreen(initial === "account" ? "account" : "preferences");
    } else setScreen(state.nextStep);
  }
  useEffect(() => {
    if (!isLoaded) return;
    if (session?.currentTask) {
      signedOnce.current = false;
      setLoading(false);
      return;
    }
    if (!isSignedIn) {
      signedOnce.current = false;
      setLoading(false);
      return;
    }
    if (signedOnce.current) return;
    signedOnce.current = true;
    resume()
      .catch((e) => {
        setError(
          e instanceof Error ? e.message : "Account settings could not load.",
        );
      })
      .finally(() => setLoading(false));
  }, [isLoaded, isSignedIn, session?.currentTask?.key]);
  function navigate(next: Screen) {
    setError("");
    setFieldErrors({});
    if (next === "location") {
      setScreen(next);
      return;
    }
    if (dirty && !window.confirm("Discard your unsaved changes?")) return;
    if (account) {
      setDraft(preferences(account));
      setName(account.displayName);
    }
    setScreen(next);
  }
  function switchAuthMode(next: "signin" | "signup") {
    if (busy || next === screen) return;
    window.history.pushState(
      null,
      "",
      `/auth?mode=${next === "signup" ? "sign-up" : "sign-in"}`,
    );
    setPassword("");
    navigate(next);
  }
  function reportError(message: string) {
    if ((screen === "signin" || screen === "signup") && !session?.currentTask)
      showAuthError(message, screen);
    else setError(message);
  }
  async function action(work: () => Promise<void>, generic?: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await work();
    } catch (e) {
      if (
        screen === "signup" &&
        typeof e === "object" &&
        e &&
        "errors" in e &&
        Array.isArray(e.errors) &&
        e.errors.some((item) => item?.code === "form_password_pwned")
      ) {
        setFieldErrors({
          password:
            "This password has appeared in a data breach. Choose a different password.",
        });
        return;
      }
      if (e instanceof AccountFailure) {
        if (e.code === "SEND_LIMIT" && (screen === "phone" || screen === "verify-phone")) {
          toast.add({
            id: "phone-send-limit",
            type: "error",
            title: e.message,
            timeout: 8000,
          });
          return;
        }
        if (e.code === "REVERIFICATION_REQUIRED") {
          setReturnAction(screen === "password" ? "password" : "phone");
          try {
            await prepareReverification();
          } catch {
            reportError(
              "Identity verification is unavailable. Please sign in again.",
            );
          }
          return;
        }
        if (e.code === "SIGN_IN_REQUIRED") {
          setAccount(null);
          setScreen("signin");
        }
        if (e.field) setFieldErrors({ [e.field]: e.message });
        else reportError(e.message);
        if (e.code === "ATTEMPT_EXPIRED") {
          setPending(null);
          setScreen("phone");
          reportError(e.message);
        }
      } else
        reportError(
          generic ?? "This request could not be completed. Please try again.",
        );
    } finally {
      setBusy(false);
    }
  }
  function form(work: () => Promise<void>, generic?: string) {
    return (event: FormEvent) => {
      event.preventDefault();
      void action(work, generic);
    };
  }
  async function completeAuth(attempt: {
    status: string | null;
    createdSessionId: string | null;
  }) {
    setPassword("");
    setCurrentPassword("");
    setCode("");
    if (attempt.status === "complete" && attempt.createdSessionId) {
      await clerk.setActive({ session: attempt.createdSessionId });
    } else if (
      attempt.status === "needs_client_trust" ||
      attempt.status === "needs_second_factor"
    ) {
      const factor = signIn?.supportedSecondFactors?.find(
        (f) => f.strategy === "email_code",
      );
      if (!factor || !signIn)
        throw new Error("A verification factor is unavailable");
      await signIn.prepareSecondFactor({
        strategy: "email_code",
        emailAddressId: factor.emailAddressId,
      });
      setSentAt(Date.now());
      setScreen("device-code");
    } else throw new Error("Additional account information is needed");
  }
  async function google() {
    if (!signIn) return;
    await signIn.authenticateWithRedirect({
      strategy: "oauth_google",
      redirectUrl: "/sso-callback",
      redirectUrlComplete: "/alerts?entry=1",
      oidcPrompt: "select_account",
    });
  }
  async function prepareReverification() {
    if (!session) throw new Error("Sign in again");
    const verification = await session.startVerification({
      level: "first_factor",
    });
    if (
      user?.passwordEnabled &&
      verification.supportedFirstFactors?.some((f) => f.strategy === "password")
    )
      setReverifyMethod("password");
    else {
      const factor = verification.supportedFirstFactors?.find(
        (f) => f.strategy === "email_code",
      );
      if (!factor || factor.strategy !== "email_code")
        throw new Error("Email verification is unavailable");
      await session.prepareFirstFactorVerification({
        strategy: "email_code",
        emailAddressId: factor.emailAddressId,
      });
      setReverifyMethod("email_code");
      setSentAt(Date.now());
    }
    setScreen("reverify");
  }
  async function sensitive(next: Screen) {
    if (dirty && !window.confirm("Discard your unsaved changes?")) return;
    if (account) {
      setDraft(preferences(account));
      setName(account.displayName);
    }
    setReturnAction(next);
    await prepareReverification();
  }
  async function requestPhone(nextPhone: string) {
    try {
      return await api<PendingPhone>("/phone/attempts", "POST", {
        phone: nextPhone,
      });
    } finally {
      // Replacement can pause SMS even when the provider request fails.
      if (account?.phone) {
        try {
          const state = await api<AccountState>();
          if (state.account) updateAccount(state.account);
        } catch {
          setAccount(null);
        }
      }
    }
  }
  const submit = (label: string) => (
    <Button
      className="primary"
      type="submit"
      isDisabled={busy}
      aria-busy={busy}
    >
      {busy ? "Please wait..." : label}
      {busy ? (
        <Loader
          className="animate-spin motion-reduce:animate-none"
          aria-hidden="true"
        />
      ) : (
        <ArrowRight aria-hidden="true" />
      )}
    </Button>
  );
  const back = (next: Screen, label = "Back") => (
    <Button
      variant="link"
      className="text-button"
      onPress={() => navigate(next)}
    >
      <ArrowLeft />
      {label}
    </Button>
  );
  const title = (text: string, intro: ReactNode) => (
    <>
      <h2 id="form-title">{text}</h2>
      <p className="form-intro">{intro}</p>
    </>
  );
  const codeField = (
    <FormField
      id="code"
      label="Verification code"
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="[0-9]{6}"
      maxLength={6}
      className="otp"
      value={code}
      onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
      required
      error={fieldErrors.code}
    />
  );
  const newPasswordFields = (
    <>
      <FormField
        id="new-password"
        label="New password"
        type="password"
        autoComplete="new-password"
        minLength={8}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        error={fieldErrors.password}
      />
      <FormField
        id="confirm-password"
        label="Confirm password"
        type="password"
        autoComplete="new-password"
        value={confirmPassword}
        onChange={(e) => setConfirmPassword(e.target.value)}
        required
        error={fieldErrors.confirmPassword}
      />
    </>
  );
  const cooldown =
    Math.max(
      0,
      Math.ceil(
        ((screen === "verify-phone"
          ? Date.parse(pending?.resendAt ?? "")
          : sentAt + 60000) -
          now) /
          1000,
      ),
    ) || 0;
  const resend = (work: () => Promise<void>) => (
    <div className="resend">
      <span>Didn't get a code?</span>
      <Button
        variant="link"
        className="text-button"
        isDisabled={busy || cooldown > 0}
        onPress={() => void action(work)}
      >
        {cooldown ? `Resend in ${cooldown}s` : "Resend code"}
      </Button>
    </div>
  );
  const phoneExpired = !!pending && Date.parse(pending.expiresAt) <= now;
  const resendPhone = async () => {
    const p = await requestPhone(pending?.phone ?? phone);
    setPending(p);
    setCode("");
    toast.add({ type: "success", title: "A new SMS code was requested." });
  };

  let content: ReactNode;
  const isAccountLoading = !isLoaded || loading;
  if (isAccountLoading)
    content = (
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
  else if (session?.currentTask)
    content = (
      <>
        {title(
          session.currentTask.key === "reset-password"
            ? "Choose a new password"
            : "Complete account verification",
          session.currentTask.key === "reset-password"
            ? `${passwordRequirements} Other sessions will be signed out.`
            : "Complete this required step to access your saved settings.",
        )}
        {session.currentTask.key === "reset-password" ? (
          <form
            onSubmit={form(async () => {
              if (password !== confirmPassword) {
                setFieldErrors({
                  confirmPassword: "The passwords do not match.",
                });
                return;
              }
              await resetTaskPassword(password);
              setPassword("");
              setConfirmPassword("");
              await clerk.setActive({ session });
              location.assign("/alerts?entry=1");
            }, "The password could not be saved. Please try again.")}
          >
            {newPasswordFields}
            {submit("Save new password")}
          </form>
        ) : session.currentTask.key === "setup-mfa" ? (
          <TaskSetupMFA redirectUrlComplete="/alerts?entry=1" />
        ) : session.currentTask.key === "choose-organization" ? (
          <TaskChooseOrganization redirectUrlComplete="/alerts?entry=1" />
        ) : (
          <p>Please sign in again to complete account verification.</p>
        )}
        <Button
          className="secondary"
          onPress={() =>
            void clerk.signOut({ redirectUrl: "/auth?mode=sign-in" })
          }
        >
          Return to sign in
        </Button>
      </>
    );
  else if (isSignedIn && !account && !["profile"].includes(screen))
    content = (
      <>
        {title(
          "Account settings unavailable",
          "Your account could not be loaded. You can still read the Bulletin.",
        )}
        <FieldError>{error}</FieldError>
        <Button className="primary" onPress={() => void action(resume)}>
          Try again
        </Button>
      </>
    );
  else if (screen === "signin" || screen === "signup")
    content = (
      <Tabs
        className="auth-tabs"
        selectedKey={screen}
        onSelectionChange={(key) => {
          if (key === "signin" || key === "signup") switchAuthMode(key);
        }}
        isDisabled={busy}
      >
        <TabsList className="mode-switch" aria-label="Account access">
          <TabsTrigger id="signin">Sign in</TabsTrigger>
          <TabsTrigger id="signup">Sign up</TabsTrigger>
        </TabsList>
        <TabsContent id={screen} key={screen}>
          {title(
            screen === "signup" ? "Create your account" : "Sign in",
            screen === "signup"
              ? "Save your personal earthquake alert settings."
              : "Access your saved earthquake alert settings.",
          )}
          <Button
            className="google"
            isDisabled={busy}
            onPress={() =>
              void action(
                google,
                "Google sign-in was not completed. Try again or use your password.",
              )
            }
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M21.6 12.2c0-.7-.1-1.5-.2-2.2H12v4.2h5.4a4.6 4.6 0 0 1-2 3v2.5h3.3c1.9-1.8 2.9-4.4 2.9-7.5"
              />
              <path
                fill="#34A853"
                d="M12 22c2.7 0 5-1 6.7-2.4L15.4 17c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3v2.6A10 10 0 0 0 12 22"
              />
              <path
                fill="#FBBC05"
                d="M6.4 13.9a6 6 0 0 1 0-3.8V7.5H3a10 10 0 0 0 0 9l3.4-2.6"
              />
              <path
                fill="#EA4335"
                d="M12 6c1.5 0 2.8.5 3.8 1.5l2.8-2.8A9.6 9.6 0 0 0 12 2a10 10 0 0 0-9 5.5l3.4 2.6A5.9 5.9 0 0 1 12 6"
              />
            </svg>
            Continue with Google
          </Button>
          <div className="divider">
            <span>or use your email</span>
          </div>
          <form
            onSubmit={form(
              async () => {
                if (screen === "signup") {
                  if (!signUp) return;
                  await signUp.create({ emailAddress: email, password });
                  await signUp.prepareEmailAddressVerification({
                    strategy: "email_code",
                  });
                  setPassword("");
                  setSentAt(Date.now());
                  setScreen("verify-email");
                } else if (signIn)
                  await completeAuth(
                    await signIn.create({ identifier: email, password }),
                  );
              },
              screen === "signin"
                ? "Check your email and password, then try again."
                : "The account could not be created. Check the password requirements, or try sign-in and recovery.",
            )}
          >
            {screen === "signup" && (
              <FormField
                id="name"
                label="Name"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={100}
                required
              />
            )}
            <FormField
              id="email"
              label="Email address"
              type="email"
              autoComplete="email"
              error={fieldErrors.email}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setFieldErrors((errors) => ({ ...errors, email: "" }));
              }}
              required
            />
            <FormField
              id="password"
              label="Password"
              labelAction={
                screen === "signin" && (
                  <Button
                    className="text-button"
                    variant="link"
                    onPress={() => setScreen("forgot")}
                  >
                    Forgot password?
                  </Button>
                )
              }
              type="password"
              autoComplete={screen === "signup" ? "off" : "current-password"}
              pattern={screen === "signup" ? passwordPattern : undefined}
              title={screen === "signup" ? passwordRequirements : undefined}
              minLength={screen === "signup" ? 8 : undefined}
              error={fieldErrors.password}
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setFieldErrors((errors) => ({ ...errors, password: "" }));
              }}
              required
            />
            {screen === "signup" && (
              <p className="support">{passwordRequirements}</p>
            )}
            {submit(screen === "signup" ? "Create account" : "Sign in")}
          </form>
          <div id="clerk-captcha" />
          <a className="guest mobile-guest" href="/">
            View Bulletin without an account
            <ArrowRight />
          </a>
        </TabsContent>
      </Tabs>
    );
  else if (screen === "verify-email" || screen === "device-code")
    content = (
      <>
        {back("signin")}
        {title(
          "Verify your email",
          screen === "device-code"
            ? "Enter the code sent to your email to confirm this device."
            : `Enter the code sent to ${email}.`,
        )}
        <form
          onSubmit={form(async () => {
            if (screen === "verify-email" && signUp)
              await completeAuth(
                await signUp.attemptEmailAddressVerification({ code }),
              );
            else if (signIn)
              await completeAuth(
                await signIn.attemptSecondFactor({
                  strategy: "email_code",
                  code,
                }),
              );
          }, "That code did not work. Check it or request a new code.")}
        >
          {codeField}
          {submit("Verify email")}
        </form>
        {resend(async () => {
          if (screen === "verify-email")
            await signUp?.prepareEmailAddressVerification({
              strategy: "email_code",
            });
          else {
            const factor = signIn?.supportedSecondFactors?.find(
              (f) => f.strategy === "email_code",
            );
            if (factor)
              await signIn?.prepareSecondFactor({
                strategy: "email_code",
                emailAddressId: factor.emailAddressId,
              });
          }
          setSentAt(Date.now());
          toast.add({
            type: "success",
            title: "A new email code was requested.",
          });
        })}
      </>
    );
  else if (["forgot", "recovery-code", "reset"].includes(screen))
    content = (
      <>
        {back("signin")}
        {title(
          screen === "forgot"
            ? "Forgot your password?"
            : screen === "reset"
              ? "Choose a new password"
              : "Check your email",
          screen === "forgot"
            ? "Enter your email to request a recovery code."
            : screen === "reset"
              ? passwordRequirements
              : "If recovery is available for this address, a code will be sent. Enter it below.",
        )}
        <form
          onSubmit={form(async () => {
            if (!signIn) return;
            if (screen === "forgot") {
              // Same UI result for existing, Google-only and unknown addresses.
              try {
                await signIn.create({
                  strategy: "reset_password_email_code",
                  identifier: email,
                });
              } catch {
                /* Enumeration-safe entry result. */
              }
              setSentAt(Date.now());
              setScreen("recovery-code");
            } else if (screen === "recovery-code") {
              await signIn.attemptFirstFactor({
                strategy: "reset_password_email_code",
                code,
              });
              setScreen("reset");
            } else {
              if (password !== confirmPassword) {
                setFieldErrors({
                  confirmPassword: "The passwords do not match.",
                });
                return;
              }
              await completeAuth(
                await signIn.resetPassword({
                  password,
                  signOutOfOtherSessions: true,
                }),
              );
            }
          }, "Recovery could not be completed. Check your code or request a new one.")}
        >
          {screen === "forgot" ? (
            <FormField
              id="email"
              label="Email address"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          ) : screen === "recovery-code" ? (
            codeField
          ) : (
            newPasswordFields
          )}
          {submit(
            screen === "forgot"
              ? "Send recovery code"
              : screen === "reset"
                ? "Save new password"
                : "Verify code",
          )}
        </form>
        {screen === "recovery-code" &&
          resend(async () => {
            try {
              await signIn?.create({
                strategy: "reset_password_email_code",
                identifier: email,
              });
            } catch {}
            setSentAt(Date.now());
            toast.add({
              type: "success",
              title: "Recovery code requested, if available.",
            });
          })}
      </>
    );
  else if (screen === "profile")
    content = (
      <>
        {title(
          "Complete your profile",
          user?.primaryEmailAddress?.emailAddress ? (
            <>
              Choose the name for your personal settings for{" "}
              <strong className="profile-email">
                {user.primaryEmailAddress.emailAddress}
              </strong>
              .
            </>
          ) : (
            "Choose the name to use for your personal settings."
          ),
        )}
        <form
          onSubmit={form(async () => {
            const next = await api<Account>("/profile", "PUT", {
              displayName: name,
            });
            updateAccount(next);
            setScreen("channels");
          })}
        >
          <FormField
            id="name"
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            autoComplete="name"
            required
            error={fieldErrors.displayName}
          />
          <div className="profile-actions">
            {submit("Continue")}
            <Button
              type="button"
              className="secondary"
              isDisabled={busy}
              onPress={() =>
                void action(
                  () => clerk.signOut({ redirectUrl: "/" }),
                  "Sign-out could not be completed. Please try again.",
                )
              }
            >
              Cancel and sign out
            </Button>
          </div>
        </form>
      </>
    );
  else if (screen === "channels")
    content = (
      <>
        {title(
          "How would you like to receive alerts?",
          "Choose Email, SMS, or both. Alerts stay off until you save your preferences.",
        )}
        <fieldset className="choices">
          <legend>Receive options</legend>
          {[
            ["sms", "SMS", "Verify a supported Philippine mobile number."],
            ["email", "Email", "Use your verified account email."],
          ].map(([id, label, text]) => (
            <label className="choice" key={id}>
              <input
                type="checkbox"
                name="channel"
                value={id}
                checked={channels.includes(id)}
                onChange={(event) =>
                  setChannels((selected) =>
                    event.target.checked
                      ? [...selected, id]
                      : selected.filter((channel) => channel !== id),
                  )
                }
              />
              <span>
                <strong>{label}</strong>
                <small>{text}</small>
              </span>
              {id === "sms" ? <Phone /> : <Mail />}
            </label>
          ))}
          <div className="choice-alternative">
            <label className="choice">
              <input
                type="checkbox"
                name="channel"
                value="none"
                checked={channels.length === 0}
                onChange={() => setChannels([])}
              />
              <span>
                <strong>Neither for now</strong>
                <small>Save your settings with both channels off.</small>
              </span>
            </label>
          </div>
        </fieldset>
        <Button
          className="primary"
          onPress={() =>
            setScreen(
              channels.includes("sms") && !account?.phone
                ? "phone"
                : "preferences",
            )
          }
        >
          Continue
          <ArrowRight />
        </Button>
      </>
    );
  else if (screen === "phone" || screen === "verify-phone")
    content = (
      <>
        {back(account?.onboardingCompleted ? "account" : "channels")}
        {title(
          screen === "phone"
            ? account?.phone
              ? "Change your mobile number"
              : "Add your mobile number"
            : "Verify your mobile number",
          screen === "phone"
            ? "We check ordinary-alert network support before requesting a code."
            : (
                <>
                  Enter the code sent to{" "}
                  <strong className="phone-destination">
                    {pending?.phone ?? "your phone"}
                  </strong>.
                </>
              ),
        )}
        {account?.phone && (
          <p className="support">
            Your current number remains linked while you verify its replacement.
            SMS is paused when you start the replacement.
          </p>
        )}
        <form
          onSubmit={form(async () => {
            if (screen === "phone") {
              const p = await requestPhone(phone);
              setPending(p);
              setPhone(p.phone);
              setScreen("verify-phone");
            } else if (pending && !phoneExpired) {
              updateAccount(
                await api<Account>("/phone/verify", "POST", {
                  attemptId: pending.id,
                  code,
                }),
              );
              setPending(null);
              setScreen("preferences");
              toast.add({
                type: "success",
                title:
                  "Mobile number verified. SMS remains off until you opt in.",
              });
            }
          })}
        >
          {screen === "phone" ? (
            <FormField
              id="phone"
              label={account?.phone ? "New mobile number" : "Mobile number"}
              type="tel"
              autoComplete="tel"
              placeholder="0917 123 4567"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
              error={fieldErrors.phone}
            />
          ) : (
            codeField
          )}
          {screen === "verify-phone" && phoneExpired ? (
            <Button
              className="primary"
              type="button"
              isDisabled={busy || cooldown > 0}
              aria-busy={busy}
              onPress={() => void action(resendPhone)}
            >
              {busy
                ? "Please wait..."
                : cooldown ? `Resend in ${cooldown}s` : "Resend code"}
              <ArrowRight aria-hidden="true" />
            </Button>
          ) : submit(
            screen === "phone"
              ? "Send verification code"
              : "Verify code",
          )}
        </form>
        {screen === "verify-phone" && (
          <>
            <div className="phone-recovery">
              <p className="support" role="status">
                {phoneExpired
                  ? "This code has expired. Request a new code."
                  : "The code expires after five minutes."}
              </p>
              {!phoneExpired && resend(resendPhone)}
            </div>
            <Button
              variant="link"
              className="text-button phone-change"
              onPress={() =>
                void action(async () => {
                  await api("/phone/attempts", "DELETE");
                  setPending(null);
                  setScreen("phone");
                })
              }
            >
              Use another number
            </Button>
          </>
        )}
        {screen === "phone" && (
          <p className="support">
            Smart and TNT numbers are currently unsupported.
          </p>
        )}
        <Button
          variant={screen === "verify-phone" ? "link" : "default"}
          className={screen === "verify-phone" ? "text-button phone-skip" : "secondary"}
          onPress={() => setScreen("preferences")}
        >
          Continue without SMS
        </Button>
      </>
    );
  else if (screen === "preferences")
    content = (
      <>
        {title(
          "Alert preferences",
          "Choose your receive options and the earthquakes you want to hear about.",
        )}
        <p className="delivery-note">
          Your preferences can be saved now. Automatic earthquake alert delivery
          is not yet available.
        </p>
        <form
          onSubmit={form(async () => {
            const finishing = !account?.onboardingCompleted;
            const next = await api<Account>("/preferences", "PUT", draft);
            updateAccount(next);
            if (finishing) location.assign("/?preferences=saved");
            else
              toast.add({ type: "success", title: "Alert preferences saved." });
          })}
        >
          <div className="switch-row">
            <span>
              <strong>Email alerts</strong>
              <small>{account?.email} · Verified</small>
            </span>
            <Switch
              aria-label="Email alerts"
              isSelected={draft.emailEnabled}
              onChange={(v) => setDraft((p) => ({ ...p, emailEnabled: v }))}
            />
          </div>
          <div className="switch-row">
            <span>
              <strong>SMS alerts</strong>
              <small>
                {account?.phone ?? "Verify a supported mobile number first."}
              </small>
            </span>
            <Switch
              aria-label="SMS alerts"
              isDisabled={!account?.phone}
              isSelected={draft.smsEnabled}
              onChange={(v) => setDraft((p) => ({ ...p, smsEnabled: v }))}
            />
          </div>
          {fieldErrors.smsEnabled && (
            <FieldError>{fieldErrors.smsEnabled}</FieldError>
          )}
          {!account?.phone && (
            <Button
              className="text-button"
              variant="link"
              onPress={() => navigate("phone")}
            >
              Add a mobile number
            </Button>
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
              Choose M1.0–M10.0. This uses the observed earthquake magnitude.
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
          <p className="rule-note">
            Verification does not enable alerts. Saving these switches records
            your choice; both can stay off.
          </p>
          {submit("Save preferences")}
        </form>
      </>
    );
  else if (screen === "location")
    content = (
      <LocationPicker
        draft={draft}
        onUse={(p) => {
          setDraft((d) => ({ ...d, ...p }));
          setScreen("preferences");
        }}
        onCancel={() => setScreen("preferences")}
      />
    );
  else if (screen === "account")
    content = (
      <>
        {title(
          "Account settings",
          "Manage your profile, verified destinations and sign-in settings.",
        )}
        <form
          onSubmit={form(async () => {
            const next = await api<Account>("/profile", "PUT", {
              displayName: name,
            });
            setAccount(next);
            setName(next.displayName);
            toast.add({ type: "success", title: "Profile saved." });
          })}
        >
          <FormField
            id="name"
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            required
            error={fieldErrors.displayName}
          />
          {submit("Save profile")}
        </form>
        <div className="account-row">
          <span>
            <strong>Email address</strong>
            <small>{account?.email} · Verified</small>
          </span>
          <Button
            variant="link"
            className="text-button"
            onPress={() => navigate("change-email")}
          >
            Change
          </Button>
        </div>
        <div className="account-row">
          <span>
            <strong>Mobile number</strong>
            <small>{account?.phone ?? "No mobile number added"}</small>
          </span>
          <Button
            variant="link"
            className="text-button"
            onPress={() =>
              void action(() =>
                account?.phone
                  ? sensitive("phone")
                  : Promise.resolve(navigate("phone")),
              )
            }
          >
            {account?.phone ? "Change" : "Add"}
          </Button>
        </div>
        <div className="account-row">
          <span>
            <strong>Password</strong>
            <small>
              {user?.passwordEnabled
                ? "Password sign-in enabled"
                : "Continue with Google"}
            </small>
          </span>
          <Button
            variant="link"
            className="text-button"
            onPress={() => void action(() => sensitive("password"))}
          >
            {user?.passwordEnabled ? "Change password" : "Add password"}
          </Button>
        </div>
        <div className="account-links">
          <Button
            variant="link"
            className="text-button"
            onPress={() => {
              if (!dirty || window.confirm("Discard your unsaved changes?"))
                void clerk.signOut({ redirectUrl: "/" });
            }}
          >
            Sign out
          </Button>
          <Button
            variant="link"
            className="danger-link"
            onPress={() => navigate("close")}
          >
            Remove account
          </Button>
        </div>
      </>
    );
  else if (screen === "reverify")
    content = (
      <>
        {back("account")}
        {title(
          "Verify your identity again",
          reverifyMethod === "password"
            ? "Enter your current password before changing sensitive account details."
            : "Enter the verification code sent to your account email.",
        )}
        <form
          onSubmit={form(async () => {
            if (!session) return;
            const verification = await session.attemptFirstFactorVerification(
              reverifyMethod === "password"
                ? { strategy: "password", password: currentPassword }
                : { strategy: "email_code", code },
            );
            if (verification.status !== "complete")
              throw new Error("Verification is incomplete");
            await getToken({ skipCache: true });
            setCurrentPassword("");
            setScreen(returnAction);
          }, "Identity verification did not work. Check your password or code and try again.")}
        >
          {reverifyMethod === "password" ? (
            <FormField
              id="current-password"
              label="Current password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          ) : (
            codeField
          )}
          {submit("Verify identity")}
        </form>
        {reverifyMethod === "email_code" && resend(prepareReverification)}
      </>
    );
  else if (screen === "password")
    content = (
      <>
        {back("account")}
        {title(
          user?.passwordEnabled
            ? "Change your password"
            : "Add password sign-in",
          `${passwordRequirements} Other sessions will be signed out.`,
        )}
        <form
          onSubmit={form(async () => {
            if (password !== confirmPassword) {
              setFieldErrors({
                confirmPassword: "The passwords do not match.",
              });
              return;
            }
            await user?.updatePassword({
              newPassword: password,
              ...(user.passwordEnabled ? { currentPassword } : {}),
              signOutOfOtherSessions: true,
            });
            setPassword("");
            setConfirmPassword("");
            setCurrentPassword("");
            setScreen("account");
            toast.add({ type: "success", title: "Password saved." });
          }, `The password could not be saved. Check your current password. ${passwordRequirements}`)}
        >
          {user?.passwordEnabled && (
            <FormField
              id="current-password"
              label="Current password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          )}
          {newPasswordFields}
          {submit("Save password")}
        </form>
      </>
    );
  else
    content = (
      <>
        {title(
          screen === "close"
            ? "Account removal is unavailable"
            : "Email change is unavailable",
          "This account action is not available in the current release.",
        )}
        <p className="support">
          {screen === "close"
            ? "Your account and saved settings remain available. You can turn both alert preferences off at any time."
            : "Keep using your current verified email. Your saved preferences are unaffected."}
        </p>
        <Button className="primary" onPress={() => setScreen("account")}>
          Back to account settings
        </Button>
      </>
    );
  return (
    <Shell
      screen={screen}
      name={account?.displayName ?? ""}
      isLoading={isAccountLoading}
      navigate={navigate}
    >
      <div
        ref={heading}
        tabIndex={-1}
        className="screen-focus"
        aria-busy={busy || isAccountLoading}
      >
        {content}
        {error &&
          (session?.currentTask ||
            !(isSignedIn && !account && screen !== "profile")) && (
            <FieldError>{error}</FieldError>
          )}
      </div>
    </Shell>
  );
}
