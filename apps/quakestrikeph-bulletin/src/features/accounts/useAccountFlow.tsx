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
import { accountPreferences as preferences, preferenceSaves, clearPreferenceSaves, type PreferenceSaves } from './preference-saves';
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
  const { isLoaded, isSignedIn, getToken, userId, sessionId } = useAuth({
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
  const [saves, setSaves] = useState<PreferenceSaves | null>(null);
  const onboardingSms = useRef(false);
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
  const signupProfileName = useRef<string | null>(null);
  const { list } = usePlaces();
  const [locationEdit, setLocationEdit] = useState<Pick<Preferences, "latitude" | "longitude" | "distanceKm"> | null>(null);
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const [leaveError, setLeaveError] = useState("");
  const [locationValidation, setLocationValidation] = useState(0);
  const [savingBeforeLeave, setSavingBeforeLeave] = useState(false);
  const allowLeave = useRef(false);
  const dirty =
    account &&
    (locationEdit !== null ||
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
    allowLeave.current = false;
    const wasAuth =
      previousScreen.current === "signin" ||
      previousScreen.current === "signup";
    const isAuth = screen === "signin" || screen === "signup";
    if (!(wasAuth && isAuth)) heading.current?.focus({ preventScroll: screen === "location" });
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
      if (dirty && (!keepsDraft || locationEdit) && !allowLeave.current) {
        const delta = nextIndex - historyIndex.current;
        undoingHistory.current = true;
        history.go(-delta);
        confirmLeave(() => history.go(delta));
        return;
      }
      allowLeave.current = false;
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
  }, [isSignedIn, screen, dirty, account, pending, locationEdit]);
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (allowLeave.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const click = (event: MouseEvent) => {
      if (allowLeave.current) return;
      const anchor = (event.target as Element).closest<HTMLAnchorElement>("a[href]");
      if (!anchor || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
        anchor.getAttribute("target") === "_blank" || anchor.hasAttribute("download") ||
        anchor.getAttribute("href")?.startsWith("#")) return;
      const destination = new URL(anchor.getAttribute("href")!, location.href);
      if (destination.href === location.href) return;
      const next = destination.origin === location.origin ? screenAtPath(destination.pathname) : null;
      if (!locationEdit && ["preferences", "location"].includes(screen) && next && ["preferences", "location"].includes(next)) return;
      event.preventDefault();
      event.stopPropagation();
      confirmLeave(() => next && ["preferences", "location", "account"].includes(next)
        ? setScreen(next) : destination.origin === location.origin ? anchor.click() : location.assign(destination.href));
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", click, true);
    };
  }, [dirty, screen, locationEdit]);
  function confirmLeave(action: () => void) {
    if (!dirty) { action(); return; }
    setLeaveError("");
    setLeaveAction(() => action);
  }
  function discardAndLeave() {
    if (!leaveAction || savingBeforeLeave) return;
    if (account) { setDraft(saves?.snapshot.preferences ?? preferences(account)); setName(account.displayName); }
    setLocationEdit(null);
    allowLeave.current = true;
    const action = leaveAction;
    setLeaveAction(null);
    action();
  }
  async function saveAndLeave() {
    if (!account || !leaveAction || savingBeforeLeave) return;
    if (locationEdit && (locationEdit.latitude === null || locationEdit.longitude === null ||
      !Number.isInteger(locationEdit.distanceKm) || locationEdit.distanceKm! < 1 || locationEdit.distanceKm! > 1000)) {
      setLeaveAction(null);
      setLocationValidation(attempt => attempt + 1);
      return;
    }
    setSavingBeforeLeave(true);
    setLeaveError("");
    try {
      let next = account;
      if (locationEdit) {
        if (!saves) throw new Error("Alert settings could not be saved. Try again.");
        next = await saves.saveConfirmed(locationEdit);
      }
      if (screen === "account" && name !== account.displayName)
        next = await api<Account>("/profile", "PUT", { displayName: name });
      if (!active.current) return;
      updateAccount(next);
      toast.add({ type: "success", title: screen === "account" ? "Changes saved." : "Alert preferences saved." });
      setLocationEdit(null);
      allowLeave.current = true;
      const action = leaveAction;
      setLeaveAction(null);
      action();
    } catch (failure) {
      if (!active.current) return;
      setLeaveError(failure instanceof Error ? failure.message : "Changes could not be saved. Try again.");
    } finally { setSavingBeforeLeave(false); }
  }
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
    const queue = preferenceSaves(`${userId}:${sessionId}`, next, async (value) => {
      const token = await getToken({ skipCache: true });
      return accountRequest<Account>(token, '/preferences', 'PUT', value);
    }, (message) => toast.add({ id: 'account-preference-save-error', type: 'error', title: message, timeout: 0 }));
    setSaves(queue);
    setAccount(queue.snapshot.account);
    setDraft(queue.snapshot.preferences);
    setName(next.displayName);
    return queue;
  }
  useEffect(() => {
    if (!saves) return;
    const sync = () => {
      setAccount(saves.snapshot.account);
      setDraft(saves.snapshot.preferences);
    };
    sync();
    return saves.subscribe(sync);
  }, [saves]);
  function savePreferences(patch: Partial<Preferences>, delay = 400) {
    if (!saves) return;
    if (patch.nearbyOnly && (draft.latitude === null || draft.longitude === null || draft.distanceKm === null)) {
      toast.add({ type: 'error', title: 'Choose an alert location and distance first.' });
      return;
    }
    saves.save(patch, delay);
  }
  async function saveOnboardingChannels() {
    if (!account || !saves) return;
    const sms = channels.includes('sms');
    const next = await saves.saveConfirmed({
      emailEnabled: channels.includes('email') && emailVerified,
      smsEnabled: sms && phoneVerified,
    });
    if (!active.current) return;
    updateAccount(next);
    onboardingSms.current = sms && !phoneVerified;
    setScreen(onboardingSms.current ? 'phone' : 'preferences', true,
      onboardingSms.current ? '/onboarding' : '/alerts');
  }
  async function finishPhone(next: Account) {
    const queue = updateAccount(next);
    setScreen('preferences', true, '/alerts');
    if (onboardingSms.current) {
      // Destination proof must commit before the separate explicit SMS opt-in.
      const enabled = await queue.saveConfirmed({ smsEnabled: true });
      if (!active.current) return;
      updateAccount(enabled);
      onboardingSms.current = false;
    }
  }
  async function skipPhone() {
    if (pending) await api('/phone/attempts', 'DELETE');
    onboardingSms.current = false;
    setPending(null);
    setScreen('preferences', true, '/alerts');
  }
  async function resume() {
    let state = await api<AccountState>();
    if (state.nextStep === "profile" && signupProfileName.current?.trim()) {
      await api<Account>("/profile", "PUT", { displayName: signupProfileName.current });
      signupProfileName.current = null;
      state = await api<AccountState>();
    }
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
      clearPreferenceSaves();
      signedOnce.current = false;
      const requested = screenAtPath(location.pathname) ?? initialScreen(initial);
      const next = isPublicAccountScreen(requested) ? requested : "signin";
      setScreen(next, true);
      setLoading(false);
      return;
    }
    if (signedOnce.current) return;
    signedOnce.current = true;
    setLoading(true);
    resume()
      .catch((e) => {
        setError(
          e instanceof Error ? e.message : "Account settings could not load.",
        );
      })
      .finally(() => setLoading(false));
  }, [isLoaded, isSignedIn, session?.currentTask?.key]);
  function navigate(next: Screen) {
    if (next === screen) return;
    setError("");
    setFieldErrors({});
    if (!locationEdit && ["preferences", "location"].includes(screen) && ["preferences", "location"].includes(next)) {
      setScreen(next);
      return;
    }
    if (dirty) { confirmLeave(() => setScreen(next)); return; }
    if (account) {
      setDraft(preferences(account));
      setName(account.displayName);
    }
    setScreen(next);
  }
  function switchAuthMode(next: "signin" | "signup") {
    if (busy || next === screen) return;
    signupProfileName.current = null;
    setPassword("");
    navigate(next);
  }
  function reportError(message: string) {
    if ((screen === "signin" || screen === "signup") && !session?.currentTask)
      showAuthError(message, screen);
    else if (isSignedIn && !account && screen !== "profile" && !session?.currentTask)
      setError(message);
    else toast.add({ id: `account-${screen}-error`, type: "error", title: message, timeout: 8000 });
  }
  async function action(work: () => Promise<void>, generic?: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await work();
    } catch (e) {
      if (!active.current) return;
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
    if (dirty) {
      confirmLeave(() => void action(async () => {
        setReturnAction(next);
        await prepareReverification(next);
      }));
      return;
    }
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
  const isAccountLoading = !isLoaded || loading ||
    (isSignedIn && !session?.currentTask && !signedOnce.current);
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
    signupProfileName,
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
    savePreferences,
    saveOnboardingChannels,
    finishPhone,
    skipPhone,
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
    setLocationEdit,
    locationValidation,
    leaveAction,
    leaveError,
    savingBeforeLeave,
    saveAndLeave,
    discardAndLeave,
    stay: () => { if (!savingBeforeLeave) setLeaveAction(null); },
    confirmLeave,
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
