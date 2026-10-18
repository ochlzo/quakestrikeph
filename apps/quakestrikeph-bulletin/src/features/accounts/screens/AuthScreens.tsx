import { ArrowRight } from "lucide-react";
import { Button } from "../../../components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../../components/ui/tabs";
import {
  BackButton,
  capitalizeNameWords,
  FormField,
  passwordPattern,
  passwordRequirements,
} from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type AuthScreenFlow = Pick<AccountFlowState, "authEntry" | "title" | "submit">;
type EmailCodeScreenFlow = Pick<
  AccountFlowState,
  "emailProof" | "title" | "codeField" | "submit" | "renderResend"
>;

export function AuthScreen({ flow }: { flow: AuthScreenFlow }) {
  const { authEntry, title, submit } = flow;
  const {
    mode: screen,
    switchAuthMode,
    busy,
    email,
    setPassword,
    name,
    setName,
    fieldErrors,
    setEmail,
    password,
    signInWithPassword,
    createAccount,
    signInWithGoogle,
    openRecovery,
  } = authEntry;
  return (
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
          onPress={() => void signInWithGoogle()}
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
          onSubmit={(event) => {
            event.preventDefault();
            void (screen === "signup" ? createAccount() : signInWithPassword());
          }}
        >
          {screen === "signup" && (
            <FormField
              id="name"
              label="Name"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={(e) => setName(capitalizeNameWords(e.target.value))}
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
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <FormField
            id="password"
            label="Password"
            labelAction={
              screen === "signin" && (
                <Button
                  type="button"
                  className="text-button"
                  variant="link"
                  isDisabled={busy}
                  onPress={openRecovery}
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
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {screen === "signup" && (
            <p className="support">{passwordRequirements}</p>
          )}
          <div id="clerk-captcha" />
          {submit(screen === "signup" ? "Create account" : "Sign in")}
        </form>
        <a className="guest mobile-guest" href="/">
          View Bulletin without an account
        </a>
      </TabsContent>
    </Tabs>
  );
}

export function EmailCodeScreen({ flow }: { flow: EmailCodeScreenFlow }) {
  const { emailProof, title, codeField, submit, renderResend } = flow;
  const { deviceVerification, email, verifyCode, resendCode } = emailProof;
  return (
    <>
      <BackButton onPress={emailProof.goBack} />
      {title(
        "Verify your email",
        deviceVerification
          ? "Enter the code sent to your email to confirm this device."
          : `Enter the code sent to ${email}.`,
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void verifyCode();
        }}
      >
        {codeField}
        {submit("Verify email")}
      </form>
      {renderResend(resendCode)}
    </>
  );
}
