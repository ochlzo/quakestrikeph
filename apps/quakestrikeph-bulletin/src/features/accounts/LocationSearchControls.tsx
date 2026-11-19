import { useId, useMemo, useRef, type RefObject } from "react";
import { MapPinSearch } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Search, SearchInput } from "../../components/ui/search";
import { Field, FieldError } from "../../components/ui/field";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "../../components/ui/combobox";
import { matchPlaces, type Place } from "./location-places";
import "./location-search-controls.css";

type Props = {
  places: Place[];
  query: string;
  searchError: string;
  locating: boolean;
  isDisabled?: boolean;
  searchAnchor?: RefObject<HTMLDivElement | null>;
  onQueryChange: (query: string) => void;
  onPlaceSelect: (place: Place) => void;
  onLocate: () => void;
};

export default function LocationSearchControls({
  places, query, searchError, locating, isDisabled, searchAnchor,
  onQueryChange, onPlaceSelect, onLocate,
}: Props) {
  const localAnchor = useRef<HTMLDivElement>(null);
  const anchor = searchAnchor ?? localAnchor;
  const errorId = useId();
  const matches = useMemo(() => matchPlaces(query, places), [query, places]);

  return (
    <div className="location-search">
      <div className="location-search-row">
        <Combobox
          className="location-search-combobox"
          aria-label="Search for a location"
          inputValue={query}
          onInputChange={onQueryChange}
          allowsCustomValue
          allowsEmptyCollection
          isDisabled={isDisabled}
          defaultFilter={() => true}
          onSelectionChange={(key) => {
            const match = matches.find(({ index }) => index === key);
            if (match) onPlaceSelect(match.p);
          }}
          menuTrigger="input"
        >
          <Field className="location-search-field-wrapper" data-invalid={!!searchError || undefined}>
            <div ref={anchor}>
              <Search className="location-search-field">
                <SearchInput
                  placeholder="Search regions, cities or municipalities"
                  aria-invalid={!!searchError}
                  aria-describedby={searchError ? errorId : undefined}
                />
                <ComboboxTrigger aria-label="Show matching locations" />
              </Search>
            </div>
            {searchError && <FieldError id={errorId}>{searchError}</FieldError>}
          </Field>
          <ComboboxContent anchor={anchor}>
            <ComboboxList
              items={matches}
              renderEmptyState={() => (
                <ComboboxEmpty className="location-search-empty">
                  No matching places. Try another name or use the map.
                </ComboboxEmpty>
              )}
            >
              {({ p, index }) => (
                <ComboboxItem id={index} textValue={`${p[0]}, ${p[1]}`}>
                  <span>{p[0]}<small className="place-context">{p[1]}</small></span>
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
        <Button type="button" variant="outline" className="location-locate" onPress={onLocate} isDisabled={isDisabled || locating}>
          <MapPinSearch aria-hidden="true" />
          {locating ? "Finding your location…" : "Use my location"}
        </Button>
      </div>
    </div>
  );
}
