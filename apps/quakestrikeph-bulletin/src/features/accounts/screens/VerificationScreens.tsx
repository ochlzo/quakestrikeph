import { TaskChooseOrganization, TaskSetupMFA } from "@clerk/react";
import { Button } from "../../../components/ui/button";
import { FormField, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type SessionTaskScreenFlow = Pick<AccountFlowState, "taskFlow" | "title" | "newPasswordFields" | "submit">;

export function SessionTaskScreen({ flow }: { flow: SessionTaskScreenFlow; }) {
  const { title, taskFlow, newPasswordFields, submit } = flow;
  const { task, savePassword, signOut } = taskFlow;
  if (!task) return null;
  return (
    <>
      {title(
        task === "reset-password"
          ? "Choose a new password"
          : "Complete account verification",
        task === "reset-password"
          ? `${passwordRequirements} Other sessions will be signed out.`
          : "Complete this required step to access your saved settings.",
      )}
      {task === "reset-password" ? (
        <form
          onSubmit={event => { event.preventDefault(); void savePassword(); }}
        >
          {newPasswordFields}
          {submit("Save new password")}
        </form>
      ) : task === "setup-mfa" ? (
        <TaskSetupMFA redirectUrlComplete="/alerts" />
      ) : task === "choose-organization" ? (
        <TaskChooseOrganization redirectUrlComplete="/alerts" />
      ) : (
        <p>Please sign in again to complete account verification.</p>
      )}
      <Button
        className="secondary"
        onPress={() => void signOut()}
      >
        Return to sign in
      </Button>
    </>
  );
}

type ReverificationScreenFlow = Pick<AccountFlowState, "reverification" | "back" | "title" | "codeField" | "submit" | "renderResend">;

export function ReverificationScreen({ flow }: { flow: ReverificationScreenFlow; }) {
  const { reverification, back, title, codeField, submit, renderResend } = flow;
  const { method: reverifyMethod, currentPassword, setCurrentPassword, verifyIdentity, resendCode } = reverification;
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
        onSubmit={event => { event.preventDefault(); void verifyIdentity(); }}
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
      {reverifyMethod === "email_code" && renderResend(resendCode)}
    </>
  );
}
