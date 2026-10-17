import { IdentityCallback, IdentityProvider, useIdentitySession } from "../../lib/auth";
import { ArrowRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Dialog, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Button } from "../../components/ui/button";
import { Toaster } from "../../components/ui/toast";
import { Shell } from "./account-ui";
import { AccountScreen, UnavailableActionScreen } from "./screens/AccountScreen";
import { AuthScreen, EmailCodeScreen } from "./screens/AuthScreens";
import { AuthLoading, PreferencesLoading, UnavailableAccountScreen } from "./screens/LoadingScreens";
import { LocationScreen } from "./screens/LocationScreen";
import { ChannelsScreen, ProfileScreen } from "./screens/OnboardingScreens";
import { PasswordScreen } from "./screens/PasswordScreen";
import { PhoneScreen } from "./screens/PhoneScreen";
import { PreferencesScreen } from "./screens/PreferencesScreen";
import { RecoveryScreen } from "./screens/RecoveryScreen";
import { ReverificationScreen, SessionTaskScreen } from "./screens/VerificationScreens";
import { useAccountFlow } from "./useAccountFlow";
import { isPublicAccountScreen } from "./routes";

export default function AccountApp({
  publishableKey,
  initial = "alerts",
  externalToaster = false,
}: {
  publishableKey: string;
  initial?: string;
  externalToaster?: boolean;
}) {
  if (!publishableKey)
    return (
      <Shell screen="signin" name="" openDestination={() => { }}>
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
    <IdentityProvider publishableKey={publishableKey} account>
      {initial === "callback" ? (
        <IdentityCallback />
      ) : (
        <SessionAccountFlow initial={initial} />
      )}
      {!externalToaster && <Toaster />}
    </IdentityProvider>
  );
}
function SessionAccountFlow({ initial }: { initial: string; }) {
  const session = useIdentitySession({ allowPending: true });
  const signedOut = session.loaded && !session.signedIn;
  const [boundary, setBoundary] = useState({ marker: session.marker, signedOut, generation: 0 });
  if (boundary.marker !== session.marker) {
    // Keep the anonymous signup draft at first sign-in. Leaving an authenticated
    // session always discards its private state, even when switching accounts.
    setBoundary({
      marker: session.marker,
      signedOut,
      generation:
        boundary.generation + (boundary.signedOut ? 0 : 1),
    });
  }
  return <AccountFlow key={boundary.generation} initial={initial} />;
}
function AccountFlow({ initial }: { initial: string; }) {
  const flow = useAccountFlow(initial);
  const {
    screen, account, isAccountLoading, heading,
    busy, navigation, taskFlow,
    isSignedIn, isLoaded,
  } = flow;
  const loadingPreferences = screen === "preferences" ||
    (isLoaded && isSignedIn && !isPublicAccountScreen(screen));
  let content: ReactNode;
  if (isAccountLoading && loadingPreferences) content = <PreferencesLoading flow={flow} />;
  else if (isAccountLoading) content = <AuthLoading flow={flow} />;
  else if (taskFlow.task) content = <SessionTaskScreen flow={flow} />;
  else if (isSignedIn && !account && !["profile"].includes(screen)) content = <UnavailableAccountScreen flow={flow} />;
  else if (screen === "signin" || screen === "signup") content = <AuthScreen flow={flow} />;
  else if (screen === "verify-email" || screen === "device-code") content = <EmailCodeScreen flow={flow} />;
  else if (["forgot", "recovery-code", "reset"].includes(screen)) content = <RecoveryScreen flow={flow} />;
  else if (screen === "profile") content = <ProfileScreen flow={flow} />;
  else if (screen === "channels") content = <ChannelsScreen flow={flow} />;
  else if (screen === "phone" || screen === "verify-phone") content = <PhoneScreen flow={flow} />;
  else if (screen === "preferences") content = <PreferencesScreen flow={flow} />;
  else if (screen === "location") content = <LocationScreen flow={flow} />;
  else if (screen === "account") content = <AccountScreen flow={flow} />;
  else if (screen === "reverify") content = <ReverificationScreen flow={flow} />;
  else if (screen === "password") content = <PasswordScreen flow={flow} />;
  else content = <UnavailableActionScreen flow={flow} />;
  return (
    <Shell
      screen={isAccountLoading && !loadingPreferences
        ? initial === "signup" ? "signup" : "signin"
        : screen}
      name={account?.displayName ?? ""}
      email={account?.email ?? undefined}
      avatarUrl={flow.identityView.avatarUrl}
      isLoading={isAccountLoading}
      openDestination={navigation.openDestination}
      signOut={navigation.signOut}
      close={navigation.close}
      modal={!taskFlow.task && location.pathname.replace(/\/$/, '') !== '/onboarding' &&
        !isPublicAccountScreen(screen) && !["profile", "channels"].includes(screen)}
      departureOpen={flow.departure.open}
    >
      <div
        key={["preferences", "location", "account"].includes(screen) ? screen : "account-flow"}
        ref={heading}
        tabIndex={-1}
        className="screen-focus"
        aria-busy={busy || isAccountLoading}
      >
        {content}
      </div>
      <UnsavedChangesDialog departure={flow.departure} />
    </Shell>
  );
}
function UnsavedChangesDialog({ departure }: { departure: ReturnType<typeof useAccountFlow>["departure"] }) {
  return <Dialog className="unsaved-dialog" isOpen={departure.open}
    UNSTABLE_portalContainer={document.getElementById('account-workspace') ?? undefined}
    onOpenChange={open => { if (!open) departure.stay(); }}
    isDismissable={!departure.saving} isKeyboardDismissDisabled={departure.saving} showCloseButton={!departure.saving}>
    <DialogHeader>
      <DialogTitle>{departure.error ? "Changes could not be saved" : "Save changes?"}</DialogTitle>
      <DialogDescription>{departure.error || "You have unsaved changes. Save them before leaving?"}</DialogDescription>
    </DialogHeader>
    <DialogFooter className="unsaved-actions">
      <Button variant="outline" onPress={departure.error ? departure.stay : departure.discardAndLeave} isDisabled={departure.saving}>
        {departure.error ? "Cancel" : "No, discard it"}
      </Button>
      <Button onPress={() => void departure.saveAndLeave()} isDisabled={departure.saving}>
        {departure.saving ? "Saving…" : departure.error ? "Retry" : "Yes"}
      </Button>
    </DialogFooter>
  </Dialog>;
}
