import { FormField, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type RecoveryScreenFlow = Pick<AccountFlowState,
  "recoveryFlow" | "back" | "title" | "codeField" | "newPasswordFields" | "submit" | "renderResend">;

export function RecoveryScreen({ flow }: { flow: RecoveryScreenFlow; }) {
  const {
    recoveryFlow, back, title, codeField, newPasswordFields, submit, renderResend,
  } = flow;
  const { stage, email, setEmail, requestCode, verifyCode, savePassword, resendCode } = recoveryFlow;
  return (
    <>
      {back("signin")}
      {title(
        stage === "request"
          ? "Forgot your password?"
          : stage === "password"
            ? "Choose a new password"
            : "Check your email",
        stage === "request"
          ? "Enter your email to request a recovery code."
          : stage === "password"
            ? passwordRequirements
            : "If recovery is available for this address, a code will be sent. Enter it below.",
      )}
      <form
        onSubmit={event => {
          event.preventDefault();
          void (stage === "request" ? requestCode() : stage === "code" ? verifyCode() : savePassword());
        }}
      >
        {stage === "request" ? (
          <FormField
            id="email"
            label="Email address"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        ) : stage === "code" ? (
          codeField
        ) : (
          newPasswordFields
        )}
        {submit(
          stage === "request"
            ? "Send recovery code"
            : stage === "password"
              ? "Save new password"
              : "Verify code",
        )}
      </form>
      {stage === "code" && renderResend(resendCode)}
    </>
  );
}
