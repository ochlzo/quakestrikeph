export type Earthquake = {
  eventId: string;
  eventTime: string;
  magnitude: number;
  latitude: number;
  longitude: number;
  depthKm: number | null;
  locationDescription: string;
  source?: { provider: string; url: string };
};

export const demoEvents: Earthquake[] = [
  { eventId: '7e00341d-b17a-4d2f-b70c-9036d562dc91', eventTime: '2024-11-12T02:24:00Z', magnitude: 5.1, latitude: 13.17, longitude: 123.75, depthKm: 10, locationDescription: '14 km E of Legazpi City, Albay' },
  { eventId: '2c332e91-8d79-41f9-b212-dc9b72a9c572', eventTime: '2024-11-11T19:18:00Z', magnitude: 4.3, latitude: 12.07, longitude: 125.2, depthKm: 32, locationDescription: '71 km SE of Calbayog City, Samar' },
  { eventId: '55c14ee6-a06d-4c6b-974f-8d7552f1a7f2', eventTime: '2024-11-11T15:52:00Z', magnitude: 3.8, latitude: 12.37, longitude: 123.94, depthKm: 18, locationDescription: '24 km N of Masbate City, Masbate' },
  { eventId: 'a499560f-3265-4c61-9170-a6c61518b4f5', eventTime: '2024-11-10T22:10:00Z', magnitude: 3.5, latitude: 13.58, longitude: 124.42, depthKm: 45, locationDescription: '62 km E of Virac, Catanduanes' },
];

export function displayTime(value: string) {
  return new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(value)) + ' (PHT)';
}

export function magnitude(value: number) { return `M${value.toFixed(1)}`; }
