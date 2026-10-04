import { useAuth, useClerk, useReverification, useSession, useUser } from "@clerk/react";
import { useSignIn, useSignUp } from "@clerk/react/legacy";
import { ArrowLeft, ArrowRight, Loader } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode, } from "react";
import { Button } from "../../components/ui/button";
import { toast } from "../../components/ui/toast";
import { FormField } from "./account-ui";
import {
  AccountFailure,
  accountRequest,
  type Account,
  type AccountState,
  type PendingPhone,
  type Preferences,
} from "./api";
import { usePlaces } from "./LocationPicker";
import { initialScreen, isPublicAccountScreen, pathForScreen, screenAtPath, writeAccountRoute, type Screen } from "./routes";
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
export function useAccountFlow(initial: string) {
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
  const [screen, updateScreen] = useState<Screen>(() => screenAtPath(location.pathname) ?? initialScreen(initial));
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
  const emailVerified =
    Boolean(account?.email) && account?.emailVerified !== false;
  const phoneVerified =
    Boolean(account?.phone) && account?.phoneVerified !== false;
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
  const historyIndex = useRef<number>(history.state?.accountIndex ?? 0);
  const undoingHistory = useRef(false);
  function setScreen(next: Screen, replace = false, path?: string) {
    if (!active.current) return;
    updateScreen(next);
    writeAccountRoute(path ?? pathForScreen(next, !!account && !account.onboardingCompleted), replace);
    historyIndex.current = history.state.accountIndex;
  }
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
    const labels: Partial<Record<Screen, string>> = {
      signin: "Sign in", signup: "Create an account", forgot: "Password recovery",
      preferences: "Alert preferences", location: "Alert location", account: "Account settings",
      password: "Password settings", phone: "Mobile number", profile: "Complete your profile", channels: "Alert setup",
    };
    document.title = `${labels[screen] ?? "Account verification"} · QuakeStrike PH Bulletin`;
  }, [screen]);
  useEffect(() => {
    const restoreRoute = () => {
      if (undoingHistory.current) { undoingHistory.current = false; return; }
      const nextIndex = history.state?.accountIndex ?? 0;
      const target = screenAtPath(location.pathname);
      if (!target) return;
      const keepsDraft = ["preferences", "location"].includes(screen) && ["preferences", "location"].includes(target);
      if (dirty && !keepsDraft) {
        if (!window.confirm("Discard your unsaved changes?")) {
          undoingHistory.current = true;
          history.go(historyIndex.current - nextIndex);
          return;
        }
        if (account) { setDraft(preferences(account)); setName(account.displayName); }
      }
      historyIndex.current = nextIndex;
      setError("");
      setFieldErrors({});
      setPassword("");
      setCurrentPassword("");
      setConfirmPassword("");
      if (!isSignedIn && !isPublicAccountScreen(target)) { setScreen("signin", true); return; }
      if (isSignedIn && (isPublicAccountScreen(target) || target === "profile")) {
        void action(async () => { await resume(); });
        return;
      }
      if (target === "password" || (target === "phone" && account?.phone && !pending)) {
        void action(async () => { setReturnAction(target); await prepareReverification(target); });
        return;
      }
      updateScreen(target === "phone" && pending ? "verify-phone" : target);
    };
    window.addEventListener("popstate", restoreRoute);
    return () => window.removeEventListener("popstate", restoreRoute);
  }, [isSignedIn, screen, dirty, account, pending]);
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
    const token = await getToken({ skipCache: method !== "GET" });
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
      const requested = screenAtPath(location.pathname) ?? initialScreen(initial);
      if (requested === "password" || (requested === "phone" && state.account?.phone && !state.pending)) {
        setReturnAction(requested);
        await prepareReverification(requested);
      } else {
        const next = isPublicAccountScreen(requested) || requested === "profile" ? "preferences" : requested;
        setScreen(next === "phone" && state.pending ? "verify-phone" : next, true, pathForScreen(next));
      }
    } else setScreen(state.nextStep, true, "/onboarding");
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
      const requested = screenAtPath(location.pathname) ?? initialScreen(initial);
      const next = isPublicAccountScreen(requested) ? requested : "signin";
      setScreen(next, true);
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
    if (["preferences", "location"].includes(screen) && ["preferences", "location"].includes(next)) {
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
        if (
          e.code === "SEND_LIMIT" &&
          (screen === "phone" || screen === "verify-phone")
        ) {
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
            await prepareReverification(screen === "password" ? "password" : "phone");
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
      redirectUrlComplete: "/alerts",
      oidcPrompt: "select_account",
    });
  }
  async function prepareReverification(target: Screen = returnAction) {
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
    setScreen("reverify", false, pathForScreen(target));
  }
  async function sensitive(next: Screen) {
    if (dirty && !window.confirm("Discard your unsaved changes?")) return;
    if (account) {
      setDraft(preferences(account));
      setName(account.displayName);
    }
    setReturnAction(next);
    await prepareReverification(next);
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
  const submit = (label: string, showArrow = true) => (
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
      ) : showArrow ? (
        <ArrowRight aria-hidden="true" />
      ) : null}
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
  const codeField = (
    <FormField
      id="code"
      label="Verification code"
      labelAction={
        screen === "verify-phone" && !phoneExpired ? (
          <Button
            type="button"
            variant="link"
            className="text-button phone-resend"
            isDisabled={busy || cooldown > 0}
            aria-label={
              cooldown
                ? `Resend code available in ${cooldown} seconds`
                : "Resend code"
            }
            onPress={() => void action(resendPhone)}
          >
            {cooldown ? `${cooldown}s` : "Resend"}
          </Button>
        ) : undefined
      }
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
  const isAccountLoading = !isLoaded || loading;
  return {
    code,
    screen,
    account,
    isAccountLoading,
    heading,
    busy,
    navigate,
    error,
    session,
    isSignedIn,
    isLoaded,
    title,
    action,
    resume,
    switchAuthMode,
    google,
    form,
    signUp,
    email,
    setPassword,
    setSentAt,
    setScreen,
    signIn,
    completeAuth,
    name,
    setName,
    fieldErrors,
    setEmail,
    setFieldErrors,
    password,
    submit,
    back,
    codeField,
    resend,
    confirmPassword,
    newPasswordFields,
    user,
    api,
    updateAccount,
    clerk,
    channels,
    setChannels,
    phoneVerified,
    pending,
    requestPhone,
    phone,
    setPending,
    setPhone,
    phoneExpired,
    cooldown,
    resendPhone,
    draft,
    emailVerified,
    setDraft,
    sensitive,
    list,
    setAccount,
    dirty,
    resetTaskPassword,
    setConfirmPassword,
    reverifyMethod,
    currentPassword,
    getToken,
    setCurrentPassword,
    returnAction,
    prepareReverification,
  };
}
export type AccountFlowState = ReturnType<typeof useAccountFlow>;
