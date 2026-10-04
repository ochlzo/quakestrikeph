import { ArrowRight } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger, } from "../../../components/ui/tabs";
import { toast } from "../../../components/ui/toast";
import { FormField, passwordPattern, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

export function AuthScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    screen, switchAuthMode, busy, title,
    action, google, form, signUp,
    email, setPassword, setSentAt, setScreen,
    signIn, completeAuth, name, setName,
    fieldErrors, setEmail, setFieldErrors, password,
    submit,
  } = flow;
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
}

export function EmailCodeScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    code, back, title, screen,
    email, form, signUp, completeAuth,
    signIn, codeField, submit, resend,
    setSentAt,
  } = flow;
  return (
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
}
