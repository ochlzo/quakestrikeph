import { ArrowRight } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { BackButton, FormField } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type PhoneScreenFlow = Pick<AccountFlowState, "phoneFlow" | "title" | "codeField" | "submit">;

export function PhoneScreen({ flow }: { flow: PhoneScreenFlow; }) {
  const { phoneFlow, title, codeField, submit } = flow;
  const {
    verifying, phone, setPhone, hasPhone, verified, destination, expired, cooldown, busy, fieldError, goBack,
    sendCode, resendCode, verifyCode, useAnotherNumber, continueWithoutSms,
  } = phoneFlow;
  return (
    <>
      <BackButton onPress={goBack} />
      {title(
        !verifying
          ? verified
            ? "Change your mobile number"
            : "Add your mobile number"
          : "Verify your mobile number",
        !verifying ? (
          "We will send a verification code to your new number."
        ) : (
          <>
            Enter the code sent to{" "}
            <strong className="phone-destination">
              {destination}
            </strong>
            .
          </>
        ),
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void (verifying ? verifyCode() : sendCode());
        }}
      >
        {!verifying ? (
          <div className="phone-number-field">
            <FormField
              id="phone"
              label={hasPhone ? "New mobile number" : "Mobile number"}
              type="tel"
              autoComplete="tel"
              placeholder="0917 123 4567"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
              error={fieldError}
            />
            <p className="support">
              Smart and TNT numbers are not supported.
            </p>
          </div>
        ) : (
          codeField
        )}
        {verifying && expired ? (
          <Button
            className="primary"
            type="button"
            isDisabled={busy || cooldown > 0}
            aria-busy={busy}
            onPress={() => void resendCode()}
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
            !verifying ? "Send code" : "Verify code",
          )
        )}
      </form>
      {verified && !verifying && (
        <p className="support">
          SMS alerts pause when you request a code.
        </p>
      )}
      {verifying && (
        <>
          <div className="phone-recovery">
            <p className="support" role="status">
              {expired
                ? "This code has expired. Request a new code."
                : "The code expires after five minutes."}
            </p>
          </div>
        </>
      )}
      {(verifying || location.pathname.replace(/\/$/, "") === "/onboarding") && <div className="phone-alternatives">
        {verifying && (
          <Button
            variant="link"
            className="text-button phone-change"
            onPress={() => void useAnotherNumber()}
          >
            Use another number
          </Button>
        )}
        <Button
          variant={verifying ? "link" : "default"}
          className={
            verifying ? "text-button phone-skip" : "secondary"
          }
          isDisabled={busy}
          onPress={() => void continueWithoutSms()}
        >
          Continue without SMS
        </Button>
      </div>}
    </>
  );
}
