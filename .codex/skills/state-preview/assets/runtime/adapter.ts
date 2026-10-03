// Customize this adapter for one target. Fictional fixtures stay in the ignored runtime folder.
export const adapter = {
  target: "account-auth",
  selector: ".auth-tabs",
  states: [
    { id: "normal", label: "Normal", data: { inputs: { name: "Alex Reyes", email: "alex@example.com", password: "SamplePass123!" } } },
    { id: "loading", label: "Loading", data: { loading: true, inputs: { name: "Alex Reyes", email: "alex@example.com", password: "SamplePass123!" } } },
    { id: "submitting", label: "Submitting", data: { submitting: true, inputs: { name: "Alex Reyes", email: "alex@example.com", password: "SamplePass123!" } } },
    { id: "field-error", label: "Field errors", data: {
      inputs: { name: "Alex Reyes", email: "alex@", password: "short" },
      errors: { email: "Enter a valid email address.", password: "Use at least 8 characters, including one lowercase letter, one uppercase letter, and one number." },
    } },
    { id: "toast-error", label: "Toast error", repeatLabel: "Add another error toast", data: {
      inputs: { name: "Alex Reyes", email: "alex@example.com", password: "SamplePass123!" },
      toast: { signin: "Check your email and password, then try again.", signup: "The account could not be created. Please try again." },
    } },
  ],
};
