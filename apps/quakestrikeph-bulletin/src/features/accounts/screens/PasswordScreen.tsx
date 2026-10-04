import { toast } from "../../../components/ui/toast";
import { FormField, passwordRequirements } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

export function PasswordScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    back, title, user, form,
    password, confirmPassword, setFieldErrors, setPassword,
    setConfirmPassword, setCurrentPassword, setScreen, currentPassword,
    newPasswordFields, submit,
  } = flow;
  return (
    <>
      {back("account")}
      {title(
        user?.passwordEnabled
          ? "Change your password"
          : "Add password sign-in",
        `${passwordRequirements} Other sessions will be signed out.`,
      )}
      <form
        onSubmit={form(async () => {
          if (password !== confirmPassword) {
            setFieldErrors({
              confirmPassword: "The passwords do not match.",
            });
            return;
          }
          await user?.updatePassword({
            newPassword: password,
            ...(user.passwordEnabled ? { currentPassword } : {}),
            signOutOfOtherSessions: true,
          });
          setPassword("");
          setConfirmPassword("");
          setCurrentPassword("");
          setScreen("account");
          toast.add({ type: "success", title: "Password saved." });
        }, `The password could not be saved. Check your current password. ${passwordRequirements}`)}
      >
        {user?.passwordEnabled && (
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
