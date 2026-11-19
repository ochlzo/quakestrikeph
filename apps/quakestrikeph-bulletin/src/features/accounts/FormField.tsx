import { Eye, EyeOff } from "lucide-react";
import { useState, type ComponentProps, type ReactNode } from "react";
import { Button } from "../../components/ui/button";
import { Field, FieldError, FieldLabel } from "../../components/ui/field";
import { Input } from "../../components/ui/input";
import "./form-field.css";

export const passwordRequirements =
  "Use at least 8 characters, including one lowercase letter, one uppercase letter, and one number.";
export const passwordPattern = "(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9]).{8,}";

export function FormField({
  id,
  label,
  labelAction,
  inputSuffix,
  inputAction,
  fieldClassName,
  error,
  type = "text",
  ...props
}: {
  id: string;
  label: string;
  labelAction?: ReactNode;
  inputSuffix?: string;
  inputAction?: ReactNode;
  fieldClassName?: string;
  error?: string;
} & ComponentProps<typeof Input>) {
  const [visible, setVisible] = useState(false);
  const [validationError, setValidationError] = useState("");
  const fieldError = error || validationError;
  const describedBy = [fieldError && `${id}-error`, props["aria-describedby"]]
    .filter(Boolean)
    .join(" ");
  return (
    <Field
      className={fieldClassName ? `field account-form-field ${fieldClassName}` : "field account-form-field"}
      data-invalid={fieldError ? true : undefined}
    >
      {labelAction ? (
        <div className="field-label-row">
          <FieldLabel htmlFor={id}>{label}</FieldLabel>
          {labelAction}
        </div>
      ) : (
        <FieldLabel htmlFor={id}>{label}</FieldLabel>
      )}
      <div
        className={
          type === "password"
            ? "password-wrap"
            : inputSuffix
              ? "input-with-suffix"
              : undefined
        }
      >
        <Input
          {...props}
          onInvalid={(event) => {
            event.preventDefault();
            props.onInvalid?.(event);
            const input = event.currentTarget;
            setValidationError(
              input.validity.valueMissing
                ? `${label} is required.`
                : input.validity.typeMismatch
                  ? "Enter a valid email address."
                  : type === "password"
                    ? passwordRequirements
                    : input.validationMessage,
            );
            input.form
              ?.querySelector<HTMLInputElement>("input:invalid")
              ?.focus();
          }}
          onChange={(event) => {
            if (event.currentTarget.validity.valid) setValidationError("");
            props.onChange?.(event);
          }}
          id={id}
          type={type === "password" && visible ? "text" : type}
          pattern={
            type === "password" && props.autoComplete === "new-password"
              ? passwordPattern
              : props.pattern
          }
          title={
            type === "password" && props.autoComplete === "new-password"
              ? passwordRequirements
              : props.title
          }
          aria-invalid={!!fieldError}
          aria-describedby={describedBy || undefined}
        />
        {inputSuffix && (
          <span
            style={{
              left: `calc(14px + ${String(props.value ?? "").length}ch + 6px)`,
            }}
          >
            {inputSuffix}
          </span>
        )}
        {inputAction}
        {type === "password" && (
          <Button
            className="show-password"
            variant="ghost"
            aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
            onPress={() => setVisible((x) => !x)}
          >
            {visible ? <EyeOff /> : <Eye />}
          </Button>
        )}
      </div>
      {fieldError && <FieldError id={`${id}-error`}>{fieldError}</FieldError>}
    </Field>
  );
}
