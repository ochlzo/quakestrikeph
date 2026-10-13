export interface Channel {
  destination: string; enabled: boolean; verified: boolean; eligible: boolean; reason: string;
}
export interface Tester {
  id: string; name: string; initials: string; status: string; onboarding_complete: boolean;
  threshold: number; nearby: boolean; limit: number;
  channels: { email: Channel; sms: Channel };
}
export interface TesterResponse { accounts: Tester[]; total: number; page: number; pages: number; }
