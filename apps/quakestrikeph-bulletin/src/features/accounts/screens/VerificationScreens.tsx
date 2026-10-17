import { IdentityTask } from "../../../lib/auth";
import { Button } from "../../../components/ui/button";
import { Spinner } from "@quakestrikeph/ui/spinner";
import { BackButton, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type SessionTaskScreenFlow = Pick<AccountFlowState, "taskFlow" | "title" | "newPasswordFields" | "submit">;

export function SessionTaskScreen({ flow }: { flow: SessionTaskScreenFlow; }) {
  const { title, taskFlow, newPasswordFields, submit } = flow;
  const { task, savePassword, signOut } = taskFlow;
  if (!task) return null;
  return (
    <>
      {title(
        task === "new-password"
          ? "Choose a new password"
          : "Complete account verification",
        task === "new-password"
          ? `${passwordRequirements} Other sessions will be signed out.`
          : "Complete this required step to access your saved settings.",
      )}
      {task === "new-password" ? (
        <form
          onSubmit={event => { event.preventDefault(); void savePassword(); }}
        >
          {newPasswordFields}
          {submit("Save new password")}
        </form>
      ) : (
        <IdentityTask />
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

type ReverificationScreenFlow = Pick<AccountFlowState, "reverification" | "title" | "codeField" | "submit" | "renderResend">;

export function ReverificationScreen({ flow }: { flow: ReverificationScreenFlow; }) {
  const { reverification, title, codeField, submit, renderResend } = flow;
  const { verifyIdentity, resendCode } = reverification;
  return (
    <>
      <BackButton onPress={reverification.goBack} />
      {title(
        reverification.sent ? "Verify your identity again" : "Verify your identity",
        reverification.sent
          ? `We sent a code to ${reverification.destination}.`
          : `To continue, we will send a verification code to ${reverification.destination}.`,
      )}
      <form
        aria-busy={reverification.busy}
        onSubmit={event => {
          event.preventDefault();
          void (reverification.sent ? verifyIdentity() : reverification.sendCode());
        }}
      >
        {reverification.sent ? <>
          {codeField}
          {submit("Verify identity")}
        </> : <Button
          type="submit"
          className="primary"
          isDisabled={reverification.busy}
        >
          {reverification.busy ? <><Spinner aria-hidden="true" /> Sending...</> : "Send verification code"}
        </Button>}
      </form>
      {reverification.sent && renderResend(resendCode)}
    </>
  );
}
