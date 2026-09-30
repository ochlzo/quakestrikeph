import { useEffect, useRef, useState } from "react";
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
  onApply: (value: string[]) => void;
};

export default function MagnitudeFilter({ value, onApply }: Props) {
  const [draft, setDraft] = useState(value.length ? value : ["all"]);
  const [search, setSearch] = useState("");
  const [focused, setFocused] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const popover = useRef<HTMLDivElement>(null);

  useEffect(() => setDraft(value.length ? value : ["all"]), [value]);

  function applySelection() {
    onApply(options.filter((band) => band.className !== "all" && draft.includes(band.className))
      .map((band) => band.className));
    setSearch("");
  }

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
        setDraft(choseAll || bands.length === 0 ? ["all"] : bands);
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
            applySelection();
          }
        }}
      >
        <div className="magnitude-filter-values">
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
          applySelection();
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
