import { TaskChooseOrganization, TaskSetupMFA } from "@clerk/react";
import { Button } from "../../../components/ui/button";
import { FormField, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

export function SessionTaskScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    title, session, form, password,
    confirmPassword, setFieldErrors, resetTaskPassword, setPassword,
    setConfirmPassword, clerk, newPasswordFields, submit,
  } = flow;
  if (!session?.currentTask) return null;
  return (
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
            location.assign("/alerts");
          }, "The password could not be saved. Please try again.")}
        >
          {newPasswordFields}
          {submit("Save new password")}
        </form>
      ) : session.currentTask.key === "setup-mfa" ? (
        <TaskSetupMFA redirectUrlComplete="/alerts" />
      ) : session.currentTask.key === "choose-organization" ? (
        <TaskChooseOrganization redirectUrlComplete="/alerts" />
      ) : (
        <p>Please sign in again to complete account verification.</p>
      )}
      <Button
        className="secondary"
        onPress={() =>
          void clerk.signOut({ redirectUrl: "/sign-in" })
        }
      >
        Return to sign in
      </Button>
    </>
  );
}

export function ReverificationScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    code, back, title, reverifyMethod,
    form, session, currentPassword, getToken,
    setCurrentPassword, setScreen, returnAction, codeField,
    submit, resend, prepareReverification,
  } = flow;
  return (
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
}
