import { useEffect, useState } from "react";
import { Dialog as AriaDialog } from "react-aria-components";
import { parseDate } from "@internationalized/date";
import { CalendarDays, CircleHelp, ExternalLink, Send, Shuffle } from "lucide-react";
import { Button } from "@quakestrikeph/ui/button";
import { Calendar } from "@quakestrikeph/ui/calendar";
import { Popover, PopoverTrigger } from "@quakestrikeph/ui/popover";
import { Field as SharedField, FieldLabel, FieldDescription, FieldError, FieldGroup } from "@quakestrikeph/ui/field";
import { InputGroup, InputGroupInput, InputGroupAddon } from "@quakestrikeph/ui/input-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@quakestrikeph/ui/select";
import { useWorkspace, initialInputs, type Inputs } from "../workspace/use-workspace";
function EventTimeField({
  inputs,
  setInputs,
  error,
}: {
  inputs: Inputs;
  setInputs: (inputs: Inputs) => void;
  error?: string;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", dismiss, true);
    return () => document.removeEventListener("keydown", dismiss, true);
  }, [open]);
  let date = null;
  try {
    date = parseDate(inputs.time.slice(0, 10));
  } catch {
    /* Empty dates remain available for validation. */
  }
  const eventTime = new Date(`${inputs.time}+08:00`);
  const display = Number.isFinite(eventTime.getTime())
    ? new Intl.DateTimeFormat("en-PH", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Manila",
      }).format(eventTime)
    : "Choose event date and time";
  return (
    <SharedField
      className="form-field wide-field event-time-field"
      data-invalid={Boolean(error) || undefined}
    >
      <FieldLabel htmlFor="time">Event time · Philippine time</FieldLabel>
      <PopoverTrigger isOpen={open} onOpenChange={setOpen}>
        <Button
          id="time"
          className="event-time-trigger"
          variant="outline"
          aria-invalid={Boolean(error)}
          aria-describedby={`time-description${error ? " time-error" : ""}`}
        >
          <span>{display}</span>
          <CalendarDays size={16} />
        </Button>
        <Popover
          className="event-time-popover"
          placement="bottom start"
          isNonModal
        >
          <AriaDialog
            aria-label="Choose event date and time"
            className="event-time-dialog"
          >
            <Calendar
              autoFocus
              aria-label="Event date"
              value={date}
              onChange={(value) => {
                if (value)
                  setInputs({
                    ...inputs,
                    time: `${value.toString()}T${inputs.time.slice(11, 16) || "00:00"}`,
                  });
              }}
            />
            <SharedField>
              <FieldLabel htmlFor="event-clock">
                Time · Philippine time
              </FieldLabel>
              <InputGroup>
                <InputGroupInput
                  id="event-clock"
                  type="time"
                  value={inputs.time.slice(11, 16)}
                  onChange={(event) => {
                    const clock = event.target.value;
                    setInputs({
                      ...inputs,
                      time: clock
                        ? `${date?.toString() || initialInputs().time.slice(0, 10)}T${clock}`
                        : "",
                    });
                  }}
                />
              </InputGroup>
            </SharedField>
            <Button onPress={() => setOpen(false)}>Done</Button>
          </AriaDialog>
        </Popover>
      </PopoverTrigger>
      {error ? (
        <FieldError id="time-error">{error}</FieldError>
      ) : (
        <FieldDescription id="time-description">
          The forecast covers exactly 24 hours from this event time.
        </FieldDescription>
      )}
    </SharedField>
  );
}

function ScenarioField({
  name,
  label,
  inputs,
  setInputs,
  errors,
  unit,
  min,
  max,
  step = "any",
  type = "number",
  description,
}: {
  name: keyof Inputs;
  label: string;
  inputs: Inputs;
  setInputs: (value: Inputs) => void;
  errors: Record<string, string>;
  unit?: string;
  min?: number;
  max?: number;
  step?: string;
  type?: string;
  description?: string;
}) {
  return (
    <SharedField
      className={`form-field ${name === "location" || name === "time" ? "wide-field" : ""}`}
      data-invalid={Boolean(errors[name]) || undefined}
    >
      <FieldLabel htmlFor={name}>{label}</FieldLabel>
      <InputGroup>
        <InputGroupInput
          id={name}
          type={type}
          value={inputs[name]}
          onChange={(event) =>
            setInputs({ ...inputs, [name]: event.target.value })
          }
          min={min}
          max={max}
          step={step}
          aria-invalid={Boolean(errors[name])}
          aria-describedby={
            [
              description && `${name}-description`,
              errors[name] && `${name}-error`,
            ]
              .filter(Boolean)
              .join(" ") || undefined
          }
        />
        {unit && <InputGroupAddon align="inline-end">{unit}</InputGroupAddon>}
      </InputGroup>
      {description && (
        <FieldDescription id={`${name}-description`}>
          {description}
        </FieldDescription>
      )}
      {errors[name] && (
        <FieldError id={`${name}-error`}>{errors[name]}</FieldError>
      )}
    </SharedField>
  );
}


export default function ScenarioForm() {
  const workspace = useWorkspace();
  const { inputs, selected } = workspace.draft;
  const active = workspace.ready;
  const errors: Record<string, string> = {};
  const preset = inputs.preset;
  const navigate = (page: string) => void workspace.navigate(page === "testers" ? "/testers" : "/");
  const setInputs = (value: Inputs) => workspace.edit({ inputs: value, selected });
  const pht = (date: Date) => new Intl.DateTimeFormat("en-PH", { timeZone: "Asia/Manila", hour: "numeric", minute: "2-digit", hour12: true }).format(date);
  function changePreset(value: string) {
    const patch =
      value === "low"
        ? {
            p1: "22",
            p4: "5",
            p5: "1",
            count: "2.3",
            radius: "18",
            q05: "1.5",
            q50: "2.4",
            q95: "3.9",
          }
        : value === "high"
          ? {
              p1: "94",
              p4: "52",
              p5: "19",
              count: "28.6",
              radius: "65",
              q05: "3.2",
              q50: "4.8",
              q95: "6.2",
            }
          : {
              p1: "82",
              p4: "28",
              p5: "8",
              count: "12.4",
              radius: "42",
              q05: "2.8",
              q50: "4.2",
              q95: "5.6",
            };
    setInputs({ ...inputs, ...patch, preset: value });

  }
  const field = (name: keyof Inputs, label: string, options = {}) => <ScenarioField name={name} label={label} inputs={inputs} setInputs={setInputs} errors={errors} {...options} />;
    return (
      <>
        <div className="page-heading">
          <div>
            <h1>New scenario</h1>
            <p>Set the earthquake and forecast your testers will receive.</p>
          </div>
        </div>
        <div className="scenario-layout">
          <form
            id="scenario-form"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              /* Unfinished edits remain in browser memory. */
            }}
            className="scenario-form"
          >
            <fieldset disabled={!active}>
              <section className="form-section">
                <div className="section-heading">
                  <h2>Earthquake</h2>
                  <span>Observed event</span>
                </div>
                <FieldGroup className="fields event-fields">
                  {field("location", "Location description", { type: "text" })}
                  {field("magnitude", "Magnitude", {
                    min: 1,
                    max: 10,
                    step: ".1",
                    unit: "M",
                  })}
                  {field("depth", "Depth", { min: 0, unit: "km" })}
                  {field("latitude", "Latitude", {
                    min: -90,
                    max: 90,
                    unit: "°",
                  })}
                  {field("longitude", "Longitude", {
                    min: -180,
                    max: 180,
                    unit: "°",
                  })}
                  <EventTimeField
                    inputs={inputs}
                    setInputs={setInputs}
                    error={errors.time}
                  />
                </FieldGroup>
              </section>
              <section className="form-section forecast-section">
                <div className="section-heading">
                  <div className="forecast-intro">
                    <h2>Forecast</h2>
                    <p className="section-intro">
                      Use a preset, then adjust the values. These are
                      illustrative estimates.
                    </p>
                  </div>
                  <SharedField className="forecast-preset-field">
                    <FieldLabel htmlFor="forecast-preset">
                      Forecast preset
                    </FieldLabel>
                    <Select
                      aria-label="Forecast preset"
                      selectedKey={preset}
                      onSelectionChange={(key) => changePreset(String(key))}
                      isDisabled={!active}
                    >
                      <SelectTrigger id="forecast-preset">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="magnitude-filter-popover">
                        <SelectItem id="low">Low activity preset</SelectItem>
                        <SelectItem id="moderate">
                          Moderate activity preset
                        </SelectItem>
                        <SelectItem id="high">High activity preset</SelectItem>
                      </SelectContent>
                    </Select>
                  </SharedField>
                </div>
                <FieldGroup className="fields three-fields">
                  {field("p1", "Chance of M1.0+", {
                    min: 0,
                    max: 100,
                    unit: "%",
                  })}
                  {field("p4", "Chance of M4.0+", {
                    min: 0,
                    max: 100,
                    unit: "%",
                  })}
                  {field("p5", "Chance of M5.0+", {
                    min: 0,
                    max: 100,
                    unit: "%",
                  })}
                </FieldGroup>
                <FieldGroup className="fields two-fields forecast-values">
                  {field("count", "Expected M1.0+ count", { min: 0 })}
                  {field("radius", "Median activity radius", {
                    min: 0.1,
                    unit: "km",
                  })}
                </FieldGroup>
                <details className="optional-values" open={Boolean(errors.q50)}>
                  <summary>
                    Maximum magnitude estimates <span>Optional</span>
                  </summary>
                  <FieldDescription>
                    Supply all three ordered values, or leave all three empty.
                  </FieldDescription>
                  <FieldGroup className="fields three-fields">
                    {field("q05", "Lower estimate · q05")}
                    {field("q50", "Median · q50")}
                    {field("q95", "Upper estimate · q95")}
                  </FieldGroup>
                </details>
              </section>
              <section className="form-section replay-section">
                <div className="section-heading">
                  <h2>Replay observations</h2>
                  <Button
                    className="randomize-replay"
                    variant="outline"
                    isDisabled
                  >
                    <Shuffle size={16} />
                    Randomize replay
                  </Button>
                </div>
                <FieldGroup className="fields two-fields">
                  {field("local", "Local observations", {
                    min: 1,
                    max: 100,
                    step: "1",
                  })}
                  {field("background", "Distant background", {
                    min: 0,
                    max: 100,
                    step: "1",
                  })}
                  {field("spread", "Positional variation", {
                    min: 0,
                    unit: "%",
                  })}
                  {field("spillover", "Local observations beyond radius", {
                    min: 0,
                    max: 100,
                    step: "1",
                  })}
                </FieldGroup>
                <FieldDescription>
                  Keep local observations inside the radius, allow spillover,
                  and include distant earthquakes. Replay observations create no
                  alerts.
                </FieldDescription>
              </section>
            </fieldset>
          </form>
          <aside className="review-rail">
            <div className="review-heading">
              <h2>Before you send</h2>
              <CircleHelp size={17} />
            </div>
            <div className="event-summary">
              <span className="magnitude">
                M{Number(inputs.magnitude || 0).toFixed(1)}
              </span>
              <div>
                <strong>
                  {inputs.location || "Add an earthquake location"}
                </strong>
                <span>
                  {inputs.depth || "0"} km deep ·{" "}
                  {inputs.time &&
                  Number.isFinite(Date.parse(inputs.time + "+08:00"))
                    ? pht(new Date(inputs.time + "+08:00"))
                    : "Set event time"}{" "}
                  PHT
                </span>
              </div>
            </div>
            <div className="forecast-summary">
              <div>
                <span>Further M1.0+ activity</span>
                <strong>{inputs.p1 || "0"}%</strong>
              </div>
              <div>
                <span>Median activity radius</span>
                <strong>{inputs.radius || "0"} km</strong>
              </div>
            </div>
            <div className="recipient-summary">
              <div className="summary-heading">
                <h3>Selected testers</h3>
                <Button variant="link" onPress={() => navigate("testers")}>
                  Edit selection
                </Button>
              </div>
              <p>{selected.length} accounts selected. Channel eligibility is provisional; check the Testers page.</p>
            </div>
            <div className="replay-summary">
              <h3>Replay coverage</h3>
              <p>Replay preparation and its diagram are not enabled in this draft slice.</p>
              <div className="diagram-legend">
                <span>
                  <i />
                  Inside radius
                </span>
                <span>
                  <i className="spill" />
                  Spillover
                </span>
                <span>
                  <i className="background" />
                  Distant
                </span>
              </div>
            </div>
            <a
              className="preview-link"
              aria-disabled="true"
              target="_blank"
              rel="noopener"
              onClick={(event) => {
                event.preventDefault();
              }}
            >
              Preview forecast page
              <ExternalLink size={15} />
            </a>
            <Button
              className="send-button"
              type="submit"
              form="scenario-form"
              isDisabled
            >
              <Send />
              Simulate and Send
            </Button>
          </aside>
        </div>
      </>
    );
}
