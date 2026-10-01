export const magnitudeBands: {
  className: string;
  label: string;
  range: { from?: number; below?: number };
}[] = [
  { className: "mag-6", label: "Above M6.0", range: { from: 6 } },
  { className: "mag-5", label: "M5.0 - M5.9", range: { from: 5, below: 6 } },
  { className: "mag-4", label: "M4.0 - M4.9", range: { from: 4, below: 5 } },
  { className: "mag-3", label: "M3.0 - M3.9", range: { from: 3, below: 4 } },
  { className: "mag-under-3", label: "Below M3.0", range: { below: 3 } },
];

export function magnitudeRangesForBands(selected: string[]) {
  return selected.length
    ? magnitudeBands
        .filter((band) => selected.includes(band.className))
        .map((band) => band.range)
    : undefined;
}

export function magnitudeBand(value: number) {
  return (
    magnitudeBands.find((band) => value >= (band.range.from ?? -Infinity)) ??
    magnitudeBands.at(-1)!
  );
}
