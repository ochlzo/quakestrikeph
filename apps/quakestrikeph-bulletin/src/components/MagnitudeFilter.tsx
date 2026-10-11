import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { magnitudeBands } from "../lib/magnitude";

const options = [
  { className: "all", label: "All magnitudes" },
  ...[...magnitudeBands].reverse(),
];

type Props = {
  value: string[];
  onChange: (value: string[]) => void;
};

export default function MagnitudeFilter({ value, onChange }: Props) {
  const draft = value.length ? value : ["all"];

  return (
    <Select
      aria-label="Magnitude ranges"
      className="magnitude-filter"
      selectionMode="multiple"
      value={draft}
      onChange={(keys) => {
        const selected = keys.map(String);
        const bands = selected.filter((key) => key !== "all");
        const choseAll = selected.includes("all") && !draft.includes("all");
        onChange(choseAll ? [] : options
          .filter((band) => band.className !== "all" && bands.includes(band.className))
          .map((band) => band.className));
      }}
    >
      <SelectTrigger className="magnitude-filter-field">
        <SelectValue className="filter-scroll-value magnitude-filter-values">
          {() => (
            <span className="magnitude-filter-value" title={options
              .filter((band) => draft.includes(band.className))
              .map((band) => band.label).join(", ")}>
              {value.length > 1 ? `${value.length} selected` : options
                .find((band) => band.className === draft[0])?.label}
            </span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="magnitude-filter-popover" placement="bottom start">
        {options.map((band) => (
          <SelectItem key={band.className} id={band.className} textValue={band.label}>
            {band.className !== "all" && (
              <i className={`dot ${band.className}`} aria-hidden="true" />
            )}
            {band.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
