import { useIdentity, type IdentityDevice, type IdentityOutcome } from "../../lib/auth";
import { ArrowRight, Loader } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode, } from "react";
import { Button } from "../../components/ui/button";
import { toast } from "../../components/ui/toast";
import { capitalizeNameWords, FormField, passwordRequirements } from "./account-ui";
import {
  AccountFailure,
  accountRequest,
  type Account,
  type AccountState,
  type PendingPhone,
  type Preferences,
} from "./api";
import { usePlaces } from "./location-places";
import { browserLocation, LocationEdit } from "./location-edit";
import { initialScreen, isPublicAccountScreen, pathForScreen, screenAtPath, writeAccountRoute, type AccountDestination, type Screen } from "./routes";
import { accountPreferences as preferences, preferenceSaves, clearPreferenceSaves, type PreferenceSaves } from './preference-saves';
import { SmsEnrollment, SmsOptInFailure } from './sms-enrollment';
import { closeAccountSettings } from './modal-navigation';
const blank: Preferences = {
  emailEnabled: false,
  smsEnabled: false,
  magnitude: 4.5,
  nearbyOnly: false,
  latitude: null,
  longitude: null,
  distanceKm: null,
};
// Failures are already presented. Ignored operations are busy or belong to an inactive session.
export type ProfileOutcome = "saved" | "failed" | "ignored";
export type ProfileFlow = {
  name: string;
  savedName: string;
  busy: boolean;
  fieldError: string | undefined;
  setName: (name: string) => void;
  clearErrors: () => void;
  saveName: () => Promise<ProfileOutcome>;
  continueProfile: () => Promise<ProfileOutcome>;
  cancelAndSignOut: () => Promise<void>;
};
export type PhoneFlow = {
  verifying: boolean;
  phone: string;
  setPhone: (phone: string) => void;
  hasPhone: boolean;
  verified: boolean;
  destination: string;
  expired: boolean;
  cooldown: number;
  busy: boolean;
  fieldError: string | undefined;
  goBack: () => void;
  sendCode: () => Promise<void>;
  resendCode: () => Promise<void>;
  verifyCode: () => Promise<void>;
  useAnotherNumber: () => Promise<void>;
  continueWithoutSms: () => Promise<void>;
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
  const identity = useIdentity(event => {
    if (event === 'authentication-fields-consumed') {
      setPassword('');
      setCode('');
    } else {
      setPassword('');
      setConfirmPassword('');
    }
  });
  const { loaded: isLoaded, signedIn: isSignedIn, requiredStep } = identity.session;
  const [screen, updateScreen] = useState<Screen>(() => screenAtPath(location.pathname) ?? initialScreen(initial));
  const [account, setAccount] = useState<Account | null>(null);
  const [pending, setPending] = useState<PendingPhone | null>(null);
  const [draft, setDraft] = useState<Preferences>({ ...blank });
  const [saves, setSaves] = useState<PreferenceSaves | null>(null);
  const [name, setName] = useState(""),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
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
  const [reverificationSent, setReverificationSent] = useState(false);
  const [phoneManagementOpen, setPhoneManagementOpen] = useState(false);
  const [devices, setDevices] = useState<IdentityDevice[]>([]);
  const [devicesStatus, setDevicesStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [devicesError, setDevicesError] = useState("");
  const devicesRequested = useRef(false);
  const [sentAt, setSentAt] = useState(0),
    [now, setNow] = useState(Date.now());
  const heading = useRef<HTMLDivElement>(null),
    signedOnce = useRef(false);
  const signupProfileName = useRef<string | null>(null);
  const { list } = usePlaces();
  const [locationEdit] = useState(() => new LocationEdit(blank, browserLocation));
  const locationChanged = useSyncExternalStore(locationEdit.subscribe,
    () => locationEdit.snapshot.dirty, () => false);
  useLayoutEffect(() => {
    locationEdit.refresh(draft);
  }, [locationEdit, draft.latitude, draft.longitude, draft.distanceKm]);
  const [leaveAction, setLeaveAction] = useState<(() => void) | null>(null);
  const [leaveError, setLeaveError] = useState("");
  const [savingBeforeLeave, setSavingBeforeLeave] = useState(false);
  const allowLeave = useRef(false);
  const dirty =
    account &&
    (locationChanged ||
      (screen === "account" && name !== account.displayName));
  const active = useRef(true);
  const enrollmentContext = useRef({ account, saves, identity, updateAccount, setScreen });
  enrollmentContext.current = { account, saves, identity, updateAccount, setScreen };
  const enrollment = useRef<SmsEnrollment | null>(null);
  const enrollmentMarker = useRef(identity.session.marker);
  function createEnrollment() {
    const marker = enrollmentContext.current.identity.session.marker;
    return new SmsEnrollment({
      request: (path, method, body) => enrollmentContext.current.identity.screenRequest(accountRequest, path, method, body),
      read: () => enrollmentContext.current,
      reconcile: next => {
        if (next) return enrollmentContext.current.updateAccount(next);
        setAccount(null);
        return null;
      },
      isCurrent: () => active.current && enrollmentContext.current.identity.session.marker === marker,
      emit: event => {
        if (event.kind === 'pending') setPending(event.pending);
        else if (event.kind === 'verified') {
          toast.add({ type: 'success', title: 'Mobile number verified.' });
          enrollmentContext.current.setScreen('preferences', true, '/alerts');
        } else toast.add({ type: 'success', title: 'SMS alerts enabled.' });
      },
    });
  }
  if (!enrollment.current || enrollmentMarker.current !== identity.session.marker) {
    enrollment.current?.dispose();
    enrollmentMarker.current = identity.session.marker;
    enrollment.current = createEnrollment();
  }
  const historyIndex = useRef<number>(history.state?.accountIndex ?? 0);
  const undoingHistory = useRef(false);
  function setScreen(next: Screen, replace = false, path?: string) {
    if (!active.current) return;
    setPhoneManagementOpen(false);
    updateScreen(next);
    writeAccountRoute(path ?? pathForScreen(next, !!account && !account.onboardingCompleted), replace);
    historyIndex.current = history.state.accountIndex;
  }
  useLayoutEffect(() => {
    active.current = true;
    if (!enrollment.current) enrollment.current = createEnrollment();
    return () => {
      active.current = false;
      locationEdit.dispose();
      enrollment.current?.dispose();
      enrollment.current = null;
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
      "remove-phone": "Remove mobile number", devices: "Signed-in devices",
      "change-email": "Change email", close: "Remove account",
    };
    document.title = `${labels[screen] ?? "Account verification"} · QuakeStrike PH Bulletin`;
  }, [screen]);
  function keepsSettingsDraft(next: Screen) {
    return ["preferences", "location"].includes(screen) && ["preferences", "location"].includes(next);
  }
  function restoreHistoryDestination(event: PopStateEvent) {
    if (undoingHistory.current) { event.stopImmediatePropagation(); undoingHistory.current = false; return; }
    const nextIndex = history.state?.accountIndex ?? 0;
    const target = screenAtPath(location.pathname);
    const keepsDraft = target && keepsSettingsDraft(target);
    if (dirty && (!keepsDraft || locationChanged) && !allowLeave.current) {
      event.stopImmediatePropagation();
      const delta = nextIndex - historyIndex.current;
      undoingHistory.current = true;
      history.go(-delta);
      requestDeparture(() => history.go(delta));
      return;
    }
    if (!target) return;
    // Local account history belongs to this mounted flow, not Astro's page swap.
    event.stopImmediatePropagation();
    allowLeave.current = false;
    historyIndex.current = nextIndex;
    setError("");
    setFieldErrors({});
    setPassword("");
    setConfirmPassword("");
    if (!isSignedIn && !isPublicAccountScreen(target)) { setScreen("signin", true); return; }
    if (isSignedIn && (isPublicAccountScreen(target) || target === "profile")) {
      void action(async () => { await resume(); });
      return;
    }
    setPhoneManagementOpen(false);
    if (target === "remove-phone" && !account?.phone) { setScreen("account", true); return; }
    if (target === "password" || target === "remove-phone" || (target === "phone" && account?.phone && !pending)) {
      void action(async () => { setReturnAction(target); await openReverification(target); });
      return;
    }
    updateScreen(target === "phone" && pending ? "verify-phone" : target);
  }
  useEffect(() => {
    window.addEventListener("popstate", restoreHistoryDestination, true);
    return () => window.removeEventListener("popstate", restoreHistoryDestination, true);
  }, [isSignedIn, screen, dirty, account, pending, locationChanged]);
  function guardBeforeUnload(event: BeforeUnloadEvent) {
    if (allowLeave.current) return;
    event.preventDefault();
    event.returnValue = "";
  }
  function interceptDepartureLink(event: MouseEvent) {
    if (allowLeave.current) return;
    const anchor = (event.target as Element).closest<HTMLAnchorElement>("a[href]");
    if (!anchor || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey ||
      anchor.getAttribute("target") === "_blank" || anchor.hasAttribute("download") ||
      anchor.getAttribute("href")?.startsWith("#")) return;
    const destination = new URL(anchor.getAttribute("href")!, location.href);
    if (destination.href === location.href) return;
    const next = destination.origin === location.origin ? screenAtPath(destination.pathname) : null;
    if (!locationChanged && next && keepsSettingsDraft(next)) return;
    event.preventDefault();
    event.stopPropagation();
    requestDeparture(() => next && ["preferences", "location", "account"].includes(next)
      ? setScreen(next) : destination.origin === location.origin ? anchor.click() : location.assign(destination.href));
  }
  useEffect(() => {
    if (!dirty) return;
    window.addEventListener("beforeunload", guardBeforeUnload);
    document.addEventListener("click", interceptDepartureLink, true);
    return () => {
      window.removeEventListener("beforeunload", guardBeforeUnload);
      document.removeEventListener("click", interceptDepartureLink, true);
    };
  }, [dirty, screen, locationChanged]);
  function requestDeparture(action: () => void) {
    if (!dirty) { action(); return; }
    setLeaveError("");
    setLeaveAction(() => action);
  }
  function discardAndLeave() {
    if (!leaveAction || savingBeforeLeave) return;
    if (account) { setDraft(saves?.snapshot.preferences ?? preferences(account)); setName(account.displayName); }
    locationEdit.cancel();
    allowLeave.current = true;
    const action = leaveAction;
    setLeaveAction(null);
    action();
  }
  async function saveAndLeave() {
    if (!account || !leaveAction || savingBeforeLeave) return;
    const location = locationChanged ? locationEdit.commit('confirmed') : null;
    if (locationChanged && !location) {
      setLeaveAction(null);
      return;
    }
    setSavingBeforeLeave(true);
    setLeaveError("");
    try {
      let next = account;
      if (location) {
        if (!saves) throw new Error("Alert settings could not be saved. Try again.");
        next = await saves.saveConfirmed({ ...location, nearbyOnly: true });
      }
      if (screen === "account" && name !== account.displayName)
        next = await writeProfile(name);
      if (!active.current) return;
      updateAccount(next);
      toast.add({ type: "success", title: screen === "account" ? "Changes saved." : "Alert preferences saved." });
      locationEdit.complete(true);
      allowLeave.current = true;
      const action = leaveAction;
      setLeaveAction(null);
      action();
    } catch (failure) {
      if (!active.current) return;
      locationEdit.complete(false);
      setLeaveError(failure instanceof Error ? failure.message : "Changes could not be saved. Try again.");
    } finally { setSavingBeforeLeave(false); }
  }
  function api<T>(path = "", method = "GET", body?: unknown) {
    return identity.screenRequest<T>(accountRequest, path, method, body);
  }
  function writeProfile(displayName: string) {
    return api<Account>("/profile", "PUT", { displayName });
  }
  async function submitProfile(intent: "name" | "onboarding"): Promise<ProfileOutcome> {
    let outcome: ProfileOutcome = "ignored";
    await action(async () => {
      outcome = "failed";
      const next = await writeProfile(name);
      if (!active.current) return;
      updateAccount(next);
      if (intent === "name") toast.add({ type: "success", title: "Profile saved." });
      else setScreen("channels");
      outcome = "saved";
    });
    return active.current ? outcome : "ignored";
  }
  function saveName() {
    return submitProfile("name");
  }
  function continueProfile() {
    return submitProfile("onboarding");
  }
  function updateAccount(next: Account) {
    const queue: PreferenceSaves = preferenceSaves(identity.session.marker, next, value =>
      identity.backgroundRequest<Account>(accountRequest, '/preferences', 'PUT', value, () => queue.cancel()), (message) => toast.add({ id: 'account-preference-save-error', type: 'error', title: message, timeout: 0 }));
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
    const next = { ...draft, ...patch };
    if (next.nearbyOnly && (next.latitude === null || next.longitude === null || next.distanceKm === null)) {
      toast.add({ type: 'error', title: 'Choose an alert location and distance first.' });
      return;
    }
    saves.save(patch, delay);
  }
  async function removeLocation() {
    if (!saves) throw new Error("Alert settings could not be saved. Try again.");
    const next = await saves.saveConfirmed({ latitude: null, longitude: null, distanceKm: null, nearbyOnly: false });
    if (!active.current) return;
    updateAccount(next);
    locationEdit.refresh(next);
    locationEdit.cancel();
    toast.add({ type: 'success', title: 'Alert location removed.' });
  }
  async function removePhone() {
    await action(async () => {
      // The screen was gated on entry; re-check so an expired proof reopens the gate.
      if (await needsRecentVerification("remove-phone")) return;
      const next = await api<Account>("/phone", "DELETE");
      if (!active.current) return;
      updateAccount(next);
      toast.add({ type: "success", title: "Mobile number removed." });
      setScreen("account");
    });
  }
  async function loadDevices() {
    setDevicesStatus("loading");
    setDevicesError("");
    const result = await identity.listDevices();
    if (!active.current) return;
    if (result.kind === "completed") { setDevices(result.devices); setDevicesStatus("ready"); return; }
    if (result.kind === "failed") { setDevicesError(result.message); setDevicesStatus("error"); }
  }
  async function signOutDevice(sessionId: string) {
    await action(async () => {
      if (await needsRecentVerification("devices")) return;
      const result = await identity.revokeDevice(sessionId);
      if (result.kind === "verification-required") {
        await openReverification("devices", true);
        return;
      }
      if (result.kind === "failed") { reportError(result.message); return; }
      if (result.kind !== "completed") return;
      toast.add({ type: "success", title: "Device signed out." });
      await loadDevices();
    });
  }
  async function signOutOtherDevices() {
    await action(async () => {
      if (await needsRecentVerification("devices")) return;
      let signedOut = 0;
      for (const device of devices.filter(value => !value.current)) {
        const result = await identity.revokeDevice(device.id);
        if (result.kind === "verification-required") {
          await openReverification("devices", true);
          return;
        }
        if (result.kind === "failed") { reportError(result.message); break; }
        if (result.kind === "ignored") return;
        signedOut++;
      }
      if (signedOut) toast.add({ type: "success", title: "Other devices signed out." });
      await loadDevices();
    });
  }
  useEffect(() => {
    if (screen !== "devices") { devicesRequested.current = false; return; }
    if (devicesRequested.current) return;
    devicesRequested.current = true;
    void loadDevices();
  }, [screen]);
  async function saveOnboardingChannels() {
    const result = await enrollment.current!.confirmChannels({ email: channels.includes('email'), sms: channels.includes('sms') });
    if (result.kind !== 'completed') return;
    setScreen(result.value ? 'phone' : 'preferences', true, result.value ? '/onboarding' : '/alerts');
  }
  async function continueWithoutSms() {
    await action(async () => {
      const result = await enrollment.current!.skip();
      if (result.kind !== 'completed') return;
      setScreen('preferences', true, '/alerts');
    });
  }
  async function resume() {
    let state = await api<AccountState>();
    if (state.nextStep === "profile" && signupProfileName.current?.trim()) {
      await writeProfile(signupProfileName.current);
      signupProfileName.current = null;
      state = await api<AccountState>();
    }
    if (state.account) updateAccount(state.account);
    enrollment.current!.resume(state.pending);
    if (state.nextStep === "complete") {
      const requested = screenAtPath(location.pathname) ?? initialScreen(initial);
      if (requested === "password" || (requested === "remove-phone" && state.account?.phone) || (requested === "phone" && state.account?.phone && !state.pending)) {
        setReturnAction(requested);
        await openReverification(requested);
      } else {
        const next = requested === "remove-phone" && !state.account?.phone ? "account" :
          isPublicAccountScreen(requested) || requested === "profile" ? "preferences" : requested;
        setScreen(next === "phone" && state.pending ? "verify-phone" : next, true, pathForScreen(next));
      }
    } else setScreen(state.nextStep, true, "/onboarding");
  }
  useEffect(() => {
    if (!isLoaded) return;
    if (requiredStep) {
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
  }, [isLoaded, isSignedIn, requiredStep]);
  function openScreen(next: Screen) {
    setPhoneManagementOpen(false);
    if (next === screen) return;
    setError("");
    setFieldErrors({});
    if (!locationChanged && keepsSettingsDraft(next)) {
      setScreen(next);
      return;
    }
    if (dirty) { requestDeparture(() => setScreen(next)); return; }
    if (account) {
      setDraft(preferences(account));
      setName(account.displayName);
    }
    setScreen(next);
  }
  function openDestination(next: AccountDestination) { openScreen(next); }
  function openEmailChange() { openScreen("change-email"); }
  function openAccountRemoval() { openScreen("close"); }
  function returnToAccount() { setScreen("account"); }
  function openPhoneManagement() {
    requestDeparture(() => {
      openScreen("account");
      setPhoneManagementOpen(true);
    });
  }
  async function openAlertPhoneSettings() {
    await action(async () => {
      setPhone(account?.phone ?? "");
      if (phoneVerified) await sensitive("phone");
      else openScreen("phone");
    });
  }
  function switchAuthMode(next: "signin" | "signup") {
    if (busy || next === screen) return;
    signupProfileName.current = null;
    setPassword("");
    openScreen(next);
  }
  function reportError(message: string) {
    if ((screen === "signin" || screen === "signup") && !requiredStep)
      showAuthError(message, screen);
    else if (isSignedIn && !account && screen !== "profile" && !requiredStep)
      setError(message);
    else toast.add({ id: `account-${screen}-error`, type: "error", title: message, timeout: 8000 });
  }
  async function action(work: () => Promise<void>, generic?: string, isCurrent = () => active.current) {
    if (busy) return;
    setBusy(true);
    setError("");
    setFieldErrors({});
    try {
      await work();
    } catch (failure) {
      if (!isCurrent()) return;
      const e = failure instanceof SmsOptInFailure ? failure.failure : failure;
      const reportFailure = (message: string) => {
        if (!isCurrent()) return;
        if (failure instanceof SmsOptInFailure) {
          if (!active.current) return;
          toast.add({ id: "account-sms-opt-in-error", type: "error", title: failure.message, description: message, timeout: 0 });
        } else reportError(message);
      };
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
          const target = screen === "password" ? "password" : screen === "remove-phone" ? "remove-phone" : "phone";
          setReturnAction(target);
          try {
            await openReverification(target, true);
            if (active.current && failure instanceof SmsOptInFailure) reportFailure(e.message);
          } catch {
            reportFailure(
              "Identity verification is unavailable. Please sign in again.",
            );
          }
          return;
        }
        if (e.code === "SIGN_IN_REQUIRED") {
          setAccount(null);
          setScreen("signin");
        }
        if (e.field) {
          setFieldErrors({ [e.field]: e.message });
          if (failure instanceof SmsOptInFailure) reportFailure(e.message);
        } else reportFailure(e.message);
        if (e.code === "ATTEMPT_EXPIRED") {
          setScreen("phone");
          reportFailure(e.message);
        }
      } else
        reportFailure(
          generic ?? "This request could not be completed. Please try again.",
        );
    } finally {
      setBusy(false);
    }
  }
  async function identityAction(work: () => Promise<IdentityOutcome>, done?: (result: Extract<IdentityOutcome, { kind: 'completed' }>) => void | Promise<void>) {
    await action(async () => {
      const result = await work();
      if (result.kind === 'failed') {
        if (result.field) setFieldErrors({ [result.field]: result.message });
        else reportError(result.message);
      } else if (result.kind === 'completed') await done?.(result);
    });
  }
  function authenticationCompleted(result: Extract<IdentityOutcome, { kind: 'completed' }>) {
    if (result.step === 'device-code') {
      setSentAt(result.sentAt!);
      setScreen('device-code');
    }
  }
  async function signInWithPassword() {
    await identityAction(() => identity.signInWithPassword(email, password), authenticationCompleted);
  }
  async function createAccount() {
    await identityAction(async () => {
      const displayName = capitalizeNameWords(name);
      setName(displayName);
      return identity.createAccount(email, password, () => { signupProfileName.current = displayName; });
    }, result => {
      if (result.step !== 'signup-code') return;
      setPassword('');
      setSentAt(result.sentAt!);
      setScreen('verify-email');
    });
  }
  async function signInWithGoogle() {
    await identityAction(() => identity.signInWithGoogle());
  }
  async function verifyEmailCode() {
    await identityAction(() => screen === 'verify-email'
      ? identity.verifySignupEmail(code) : identity.verifySignInEmail(code), authenticationCompleted);
  }
  async function resendEmailCode() {
    await identityAction(() => screen === 'verify-email'
      ? identity.resendSignupEmail() : identity.resendSignInEmail(), result => {
      setSentAt(result.sentAt!);
      toast.add({ type: 'success', title: 'A new email code was requested.' });
    });
  }
  async function requestRecoveryCode() {
    await identityAction(() => identity.requestRecoveryCode(email), result => {
      setSentAt(result.sentAt!);
      setScreen('recovery-code');
    });
  }
  async function verifyRecoveryCode() {
    await identityAction(() => identity.verifyRecoveryCode(code), () => setScreen('reset'));
  }
  function passwordsMatch() {
    if (password === confirmPassword) return true;
    setFieldErrors({ confirmPassword: 'The passwords do not match.' });
    return false;
  }
  async function saveRecoveredPassword() {
    await identityAction(() => passwordsMatch() ? identity.saveRecoveredPassword(password) : Promise.resolve({ kind: 'ignored' }), authenticationCompleted);
  }
  async function resendRecoveryCode() {
    await identityAction(() => identity.resendRecoveryCode(email), result => {
      setSentAt(result.sentAt!);
      toast.add({ type: 'success', title: 'Recovery code requested, if available.' });
    });
  }
  async function openReverification(target: Screen = returnAction, force = false) {
    setReturnAction(target);
    if (!force && await identity.hasRecentVerification()) {
      setScreen(target);
      return true;
    }
    setReverificationSent(false);
    setCode('');
    setScreen('reverify', false, pathForScreen(target));
    return true;
  }
  async function sendIdentityCode() {
    const result = await identity.prepareReverification('email-code');
    if (result.kind === 'failed') throw new Error(result.message);
    if (result.kind !== 'completed') return false;
    if (result.step !== 'email-code') return false;
    if (result.sentAt !== undefined) setSentAt(result.sentAt);
    setCode('');
    setReverificationSent(true);
    return true;
  }
  async function verifyIdentity() {
    await identityAction(() => identity.verifyIdentity('email-code', code), () => {
      setScreen(returnAction);
    });
  }
  async function resendIdentityCode() {
    await action(async () => { await sendIdentityCode(); });
  }
  async function needsRecentVerification(target: Screen) {
    if (await identity.hasRecentVerification()) return false;
    setReturnAction(target);
    await openReverification(target, true);
    return true;
  }
  async function savePassword() {
    await identityAction(async () => {
      if (!passwordsMatch()) return { kind: 'ignored' };
      if (await needsRecentVerification('password')) return { kind: 'ignored' };
      const result = await identity.savePassword(password);
      return result.kind === 'failed' ? { ...result, message: result.message + ' ' + passwordRequirements } : result;
    }, async () => {
      setPassword('');
      setConfirmPassword('');
      setScreen('account');
      toast.add({ type: 'success', title: 'Password saved.' });
    });
  }
  async function openPasswordSettings() {
    await action(() => sensitive('password'));
  }
  async function openPhoneSettings() {
    await action(() => account?.phone ? sensitive('phone') : Promise.resolve(openScreen('phone')));
  }
  async function saveTaskPassword() {
    await identityAction(() => passwordsMatch() ? identity.saveRequiredPassword(password) : Promise.resolve({ kind: 'ignored' }), () => location.assign('/alerts'));
  }
  async function endSession(redirectUrl: '/' | '/sign-in') {
    await identityAction(() => identity.signOut(redirectUrl));
  }
  function cancelProfileAndSignOut() { return endSession("/"); }
  async function signOutFromAccount() {
    if (!dirty || window.confirm("Discard your unsaved changes?")) await endSession("/");
  }
  function signOutFromShell() { requestDeparture(() => void endSession("/")); }
  function signOutTask() { return endSession("/sign-in"); }
  async function sensitive(next: Screen) {
    setPhoneManagementOpen(false);
    if (dirty) {
      requestDeparture(() => void action(async () => {
        setReturnAction(next);
        await openReverification(next);
      }));
      return;
    }
    if (account) {
      setDraft(preferences(account));
      setName(account.displayName);
    }
    setReturnAction(next);
    await openReverification(next);
  }
  async function sendCode() {
    await action(async () => {
      if (phoneVerified && await needsRecentVerification('phone')) return;
      const result = await enrollment.current!.send(phone);
      if (result.kind !== 'completed') return;
      setPhone(result.value.phone);
      setScreen("verify-phone");
    });
  }
  async function resendCode() {
    await action(async () => {
      if (phoneVerified && await needsRecentVerification('verify-phone')) return;
      const result = await enrollment.current!.resend(phone);
      if (result.kind !== 'completed') return;
      setCode("");
      toast.add({ type: "success", title: "A new SMS code was requested." });
    });
  }
  async function verifyCode() {
    await action(async () => {
      if (phoneVerified && await needsRecentVerification('verify-phone')) return;
      await enrollment.current!.verify(code, now);
    });
  }
  async function useAnotherNumber() {
    await action(async () => {
      const result = await enrollment.current!.changeNumber();
      if (result.kind !== 'completed') return;
      setScreen("phone");
    });
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
  const phoneState = enrollment.current.view(now);
  const cooldown = screen === 'verify-phone' ? phoneState.cooldown :
    Math.max(
      0,
      Math.ceil(
        ((sentAt + 60000) -
          now) /
        1000,
      ),
    ) || 0;
  const renderResend = (work: () => Promise<void>) => (
    <div className="resend">
      <span>Didn't get a code?</span>
      <Button
        variant="link"
        className="text-button"
        isDisabled={busy || cooldown > 0}
        onPress={() => void work()}
      >
        {cooldown ? `Resend in ${cooldown}s` : "Resend code"}
      </Button>
    </div>
  );
  const phoneExpired = phoneState.expired;
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
            onPress={() => void resendCode()}
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
    (isSignedIn && !requiredStep && !signedOnce.current);
  const profile: ProfileFlow = {
    name, savedName: account?.displayName ?? "", busy,
    fieldError: fieldErrors.displayName,
    setName, clearErrors: () => setFieldErrors({}),
    saveName, continueProfile, cancelAndSignOut: cancelProfileAndSignOut,
  };
  const phoneFlow: PhoneFlow = {
    verifying: screen === "verify-phone", phone, setPhone,
    hasPhone: Boolean(account?.phone), verified: phoneVerified,
    destination: pending?.phone ?? "your phone", expired: phoneExpired, cooldown, busy,
    fieldError: fieldErrors.phone, goBack: () => openScreen(account?.onboardingCompleted ? "account" : "channels"),
    sendCode, resendCode, verifyCode, useAnotherNumber, continueWithoutSms,
  };
  const authEntry = {
    mode: screen === "signup" ? "signup" as const : "signin" as const,
    busy, name, setName, email, password,
    fieldErrors: { email: fieldErrors.email, password: fieldErrors.password },
    setEmail: (value: string) => { setEmail(value); setFieldErrors(errors => ({ ...errors, email: "" })); },
    setPassword: (value: string) => { setPassword(value); setFieldErrors(errors => ({ ...errors, password: "" })); },
    switchAuthMode, signInWithPassword, createAccount, signInWithGoogle,
    openRecovery: () => { setPassword(''); setScreen("forgot"); },
  };
  const emailProof = {
    deviceVerification: screen === "device-code", email, goBack: () => openScreen("signin"),
    verifyCode: verifyEmailCode, resendCode: resendEmailCode,
  };
  const recoveryFlow = {
    stage: screen === "forgot" ? "request" as const : screen === "recovery-code" ? "code" as const : "password" as const,
    email, setEmail, goBack: () => openScreen("signin"), requestCode: requestRecoveryCode, verifyCode: verifyRecoveryCode,
    savePassword: saveRecoveredPassword, resendCode: resendRecoveryCode,
  };
  const passwordFlow = {
    hasPassword: identity.view.hasPassword, savePassword, goBack: () => openScreen("account"),
  };
  const accountEmail = account?.email;
  const emailAt = accountEmail?.lastIndexOf('@') ?? -1;
  const reverification = {
    goBack: () => openScreen("account"), verifyIdentity, resendCode: resendIdentityCode,
    sent: reverificationSent, busy,
    destination: accountEmail && emailAt > 0 ? `${accountEmail[0]}•••${accountEmail.slice(emailAt)}` : 'your account email',
    sendCode: () => action(async () => { await sendIdentityCode(); }),
  };
  const identityView = identity.view;
  const taskFlow = { task: requiredStep, savePassword: saveTaskPassword, signOut: signOutTask };
  const navigation = { openDestination, signOut: signOutFromShell, close: () => requestDeparture(closeAccountSettings) };
  const accountActions = {
    openEmailChange, openAccountRemoval, signOut: signOutFromAccount,
    openPhoneRemoval: () => { void action(() => sensitive("remove-phone")); },
    openPhoneManagement,
    openDevices: () => openScreen("devices"),
    returnToAccount,
    removePhone,
  };
  const unavailableAction = { removing: screen === "close", returnToAccount };
  const phoneManagement = {
    open: phoneManagementOpen && screen === "account" && Boolean(account?.phone),
    close: () => setPhoneManagementOpen(false),
  };
  const devicesFlow = {
    list: devices,
    loading: devicesStatus === "loading" || devicesStatus === "idle",
    error: devicesStatus === "error" ? devicesError : "",
    refresh: loadDevices,
    signOut: signOutDevice,
    signOutOthers: signOutOtherDevices,
  };
  const preferencesNavigation = { openPhone: openAlertPhoneSettings, openLocation: () => setScreen("location") };
  const departure = {
    open: Boolean(leaveAction), error: leaveError, saving: savingBeforeLeave,
    saveAndLeave, discardAndLeave,
    stay: () => { if (!savingBeforeLeave) setLeaveAction(null); },
  };
  return {
    navigation, accountActions, unavailableAction, preferencesNavigation, departure, phoneManagement,
    devices: devicesFlow,
    authEntry, emailProof, recoveryFlow, renderResend,
    passwordFlow, reverification, openPasswordSettings, openPhoneSettings,
    identityView, taskFlow,
    profile,
    phoneFlow,
    screen,
    account,
    isAccountLoading,
    heading,
    busy,
    error,
    isSignedIn,
    isLoaded,
    title,
    action,
    resume,
    fieldErrors,
    submit,
    codeField,
    newPasswordFields,
    savePreferences,
    removeLocation,
    saveOnboardingChannels,
    channels,
    setChannels,
    phoneVerified,
    draft,
    emailVerified,
    setDraft,
    list,
    locationEdit,
  };
}
export type AccountFlowState = ReturnType<typeof useAccountFlow>;
