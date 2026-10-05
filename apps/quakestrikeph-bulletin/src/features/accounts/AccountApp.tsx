import { AuthenticateWithRedirectCallback, ClerkProvider, useAuth } from "@clerk/react";
import { ArrowRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { FieldError } from "../../components/ui/field";
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
}: {
  publishableKey: string;
  initial?: string;
}) {
  if (!publishableKey)
    return (
      <Shell screen="signin" name="" navigate={() => { }}>
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
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      signInFallbackRedirectUrl="/alerts"
      signUpFallbackRedirectUrl="/alerts"
      taskUrls={{
        "reset-password": "/sign-in",
        "setup-mfa": "/sign-in",
        "choose-organization": "/sign-in",
      }}
    >
      {initial === "callback" ? (
        <AuthenticateWithRedirectCallback
          signInUrl="/sign-in"
          signUpUrl="/sign-up"
          signInFallbackRedirectUrl="/alerts"
          signUpFallbackRedirectUrl="/alerts"
        />
      ) : (
        <SessionAccountFlow initial={initial} />
      )}
      <Toaster />
    </ClerkProvider>
  );
}
function SessionAccountFlow({ initial }: { initial: string; }) {
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
function AccountFlow({ initial }: { initial: string; }) {
  const flow = useAccountFlow(initial);
  const {
    screen, account, isAccountLoading, heading,
    busy, navigate, error, session,
    isSignedIn, isLoaded,
  } = flow;
  const loadingPreferences = screen === "preferences" ||
    (isLoaded && isSignedIn && !isPublicAccountScreen(screen));
  let content: ReactNode;
  if (isAccountLoading && loadingPreferences) content = <PreferencesLoading flow={flow} />;
  else if (isAccountLoading) content = <AuthLoading flow={flow} />;
  else if (session?.currentTask) content = <SessionTaskScreen flow={flow} />;
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
