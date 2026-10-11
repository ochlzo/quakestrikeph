import { BackButton, FormField, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type PasswordScreenFlow = Pick<AccountFlowState, "passwordFlow" | "title" | "newPasswordFields" | "submit">;

export function PasswordScreen({ flow }: { flow: PasswordScreenFlow; }) {
  const {
    passwordFlow, title, newPasswordFields, submit,
  } = flow;
  const { hasPassword, currentPassword, setCurrentPassword, savePassword } = passwordFlow;
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
        {hasPassword && (
          <FormField
            id="current-password"
            label="Current password"
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        )}
        {newPasswordFields}
        {submit("Save password")}
      </form>
    </>
  );
}
