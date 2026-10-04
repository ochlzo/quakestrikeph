import { toast } from "../../../components/ui/toast";
import { FormField, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

export function RecoveryScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    code, back, title, screen,
    form, signIn, email, setSentAt,
    setScreen, password, confirmPassword, setFieldErrors,
    completeAuth, setEmail, codeField, newPasswordFields,
    submit, resend,
  } = flow;
  return (
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
          } catch { }
          setSentAt(Date.now());
          toast.add({
            type: "success",
            title: "Recovery code requested, if available.",
          });
        })}
    </>
  );
}
