export type DeliveryStatus = "pending" | "skipped" | "accepted" | "delivered" | "failed" | "unknown";
export type ScenarioResult = {
  event_id: string;
  submitted_at_ms: number;
  event: { location: string; magnitude: number; depth_km: number; event_time_ms: number };
  forecast_url: string;
  queue_status: "pending" | "enqueued";
  counts: Record<DeliveryStatus, number>;
  recipients?: { user_id: string; channel: "email" | "sms"; name?: string; destination?: string; status: DeliveryStatus; reason: string }[];
};
export type SubmissionRequest = {
  session_id: string;
  inputs: import("./scenarios-v1").ScenarioInputs;
  scenario: import("./scenarios-v1").PreparedScenario;
  selected: string[];
};
