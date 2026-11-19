const countFormat = new Intl.NumberFormat("en-PH", { maximumFractionDigits: 2 });

export function formatForecastCount(value: number) {
  return countFormat.format(value);
}

export function formatForecastPercent(value: number) {
  if (value > 0 && value < 0.005) return "<1%";
  if (value < 1 && value >= 0.995) return ">99%";
  return `${Math.round(value * 100)}%`;
}
