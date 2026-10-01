import { useEffect, useRef, useState } from "react";
import { Stone } from "lucide-react";
import {
  Combobox,
  ComboboxChip,
  ComboboxChipList,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@/components/ui/combobox";
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
  const [search, setSearch] = useState("");
  const [focused, setFocused] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const values = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const row = values.current;
      if (!row) return;
      row.scrollTo({
        left: row.scrollWidth,
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return (
    <Combobox
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
        setSearch("");
      }}
      inputValue={search}
      onInputChange={setSearch}
      menuTrigger="focus"
      allowsEmptyCollection
    >
      <ComboboxChips
        ref={anchor}
        className="magnitude-filter-field"
        data-all-magnitudes={draft.includes("all") || undefined}
        onFocus={() => setFocused(true)}
        onBlur={(event) => {
          const next = event.relatedTarget as Node | null;
          if (!anchor.current?.contains(next) && !popover.current?.contains(next)) {
            setFocused(false);
            setSearch("");
          }
        }}
      >
        <Stone className="magnitude-filter-icon size-5" aria-hidden="true" />
        <div ref={values} className="magnitude-filter-values">
          {!draft.includes("all") && <ComboboxChipList<(typeof options)[number]>>
            {(band) => (
              <ComboboxChip
                id={band.className}
                textValue={band.label}
              >
                <i className={`dot ${band.className}`} aria-hidden="true" />
                {band.label}
              </ComboboxChip>
            )}
          </ComboboxChipList>}
          <ComboboxChipsInput
            placeholder={draft.includes("all")
              ? focused ? "Search ranges" : "All magnitudes"
              : "Add range"}
            maxLength={50}
          />
        </div>
        <ComboboxTrigger
          className="magnitude-filter-trigger"
          aria-label="Show magnitude ranges"
        />
      </ComboboxChips>
      <ComboboxContent
        ref={popover}
        anchor={anchor}
        className="magnitude-filter-popover"
        shouldCloseOnInteractOutside={(element) => {
          if (anchor.current?.contains(element)) return false;
          setFocused(false);
          setSearch("");
          return true;
        }}
      >
        <ComboboxList
          items={options}
          renderEmptyState={() => <ComboboxEmpty>No matching ranges.</ComboboxEmpty>}
        >
          {(band) => (
            <ComboboxItem id={band.className} textValue={band.label}>
              {band.className !== "all" && (
                <i className={`dot ${band.className}`} aria-hidden="true" />
              )}
              {band.label}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
