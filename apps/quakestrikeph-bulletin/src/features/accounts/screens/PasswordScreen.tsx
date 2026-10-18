import { BackButton, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type PasswordScreenFlow = Pick<AccountFlowState, "passwordFlow" | "title" | "newPasswordFields" | "submit">;

export function PasswordScreen({ flow }: { flow: PasswordScreenFlow; }) {
  const {
    passwordFlow, title, newPasswordFields, submit,
  } = flow;
  const { hasPassword, savePassword } = passwordFlow;
  return (
    <>
      <BackButton onPress={passwordFlow.goBack} />
      {title(
        hasPassword
          ? "Change your password"
          : "Add password sign-in",
        `${passwordRequirements} Other sessions will be signed out.`,
      )}
      <form
        onSubmit={event => { event.preventDefault(); void savePassword(); }}
      >
        {newPasswordFields}
        {submit("Save password")}
      </form>
    </>
  );
}
