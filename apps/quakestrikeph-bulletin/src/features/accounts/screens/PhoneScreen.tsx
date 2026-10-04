import { ArrowRight } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/toast";
import { FormField } from "../account-ui";
import { type Account } from "../api";
import type { AccountFlowState } from "../useAccountFlow";

export function PhoneScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    code, back, account, title,
    screen, phoneVerified, pending, form,
    requestPhone, phone, setPending, setPhone,
    setScreen, phoneExpired, updateAccount, api,
    fieldErrors, codeField, busy, cooldown,
    action, resendPhone, submit,
  } = flow;
  return (
    <>
      {back(account?.onboardingCompleted ? "account" : "channels")}
      {title(
        screen === "phone"
          ? phoneVerified
            ? "Change your mobile number"
            : "Add your mobile number"
          : "Verify your mobile number",
        screen === "phone" ? (
          "We check ordinary-alert network support before requesting a code."
        ) : (
          <>
            Enter the code sent to{" "}
            <strong className="phone-destination">
              {pending?.phone ?? "your phone"}
            </strong>
            .
          </>
        ),
      )}
      {phoneVerified && (
        <p className="support">
          Your current number remains linked while you verify its replacement.
          SMS is paused when you start the replacement.
        </p>
      )}
      <form
        onSubmit={form(async () => {
          if (screen === "phone") {
            const p = await requestPhone(phone);
            setPending(p);
            setPhone(p.phone);
            setScreen("verify-phone");
          } else if (pending && !phoneExpired) {
            updateAccount(
              await api<Account>("/phone/verify", "POST", {
                attemptId: pending.id,
                code,
              }),
            );
            setPending(null);
            setScreen("preferences");
            toast.add({
              type: "success",
              title: "Mobile number verified.",
            });
          }
        })}
      >
        {screen === "phone" ? (
          <FormField
            id="phone"
            label={account?.phone ? "New mobile number" : "Mobile number"}
            type="tel"
            autoComplete="tel"
            placeholder="0917 123 4567"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            required
            error={fieldErrors.phone}
          />
        ) : (
          codeField
        )}
        {screen === "verify-phone" && phoneExpired ? (
          <Button
            className="primary"
            type="button"
            isDisabled={busy || cooldown > 0}
            aria-busy={busy}
            onPress={() => void action(resendPhone)}
          >
            {busy
              ? "Please wait..."
              : cooldown
                ? `Resend in ${cooldown}s`
                : "Resend code"}
            <ArrowRight aria-hidden="true" />
          </Button>
        ) : (
          submit(
            screen === "phone" ? "Send verification code" : "Verify code",
          )
        )}
      </form>
      {screen === "verify-phone" && (
        <>
          <div className="phone-recovery">
            <p className="support" role="status">
              {phoneExpired
                ? "This code has expired. Request a new code."
                : "The code expires after five minutes."}
            </p>
          </div>
        </>
      )}
      {screen === "phone" && (
        <p className="support">
          Smart and TNT numbers are currently unsupported.
        </p>
      )}
      <div className="phone-alternatives">
        {screen === "verify-phone" && (
          <Button
            variant="link"
            className="text-button phone-change"
            onPress={() =>
              void action(async () => {
                await api("/phone/attempts", "DELETE");
                setPending(null);
                setScreen("phone");
              })
            }
          >
            Use another number
          </Button>
        )}
        <Button
          variant={screen === "verify-phone" ? "link" : "default"}
          className={
            screen === "verify-phone" ? "text-button phone-skip" : "secondary"
          }
          onPress={() => setScreen("preferences")}
        >
          Continue without SMS
        </Button>
      </div>
    </>
  );
}
