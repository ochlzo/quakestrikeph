import { useEffect, useState } from "react";

export type Place = [string, string, number, number, string];
let placeRequest: Promise<Place[]> | undefined;
function places() {
  return (placeRequest ??= fetch("/assets/accounts/philippine-places.json")
    .then((r) => {
      if (!r.ok) throw new Error("Place search unavailable");
      return r.json() as Promise<Place[]>;
    })
    .catch((error) => {
      placeRequest = undefined;
      throw error;
    }));
}
const normalized = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
export function matchPlaces(query: string, list: Place[]) {
  const terms = normalized(query.trim()).split(/\s+/);
  const text = normalized(query.trim());
  const rank = (p: Place) =>
    normalized(p[0]) === text
      ? 0
      : normalized(p[0]).startsWith(text)
        ? 1
        : normalized(p[0]).includes(text)
          ? 2
          : 3;
  return query.trim().length < 2
    ? []
    : list
        .map((p, index) => ({ p, index }))
        .filter(({ p }) =>
          terms.every((t) =>
            normalized(`${p[0]} ${p[1]} ${p[4]}`).includes(t),
          ),
        )
        .sort((a, b) => rank(a.p) - rank(b.p))
        .slice(0, 20);
}

export function locationLabel(
  latitude: number | null,
  longitude: number | null,
  list: Place[],
) {
  if (latitude === null || longitude === null)
    return "Choose your alert location";
  let closest: Place | undefined,
    distance = Infinity;
  for (const p of list) {
    const d =
      (p[2] - latitude) ** 2 +
      ((p[3] - longitude) * Math.cos((latitude * Math.PI) / 180)) ** 2;
    if (d < distance) {
      distance = d;
      closest = p;
    }
  }
  return closest
    ? `${distance > 0.000001 ? "Pin near " : ""}${closest[0]}, ${closest[1]}`
    : "Your selected map pin";
}
export function usePlaces() {
  const [list, setList] = useState<Place[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    places()
      .then((x) => {
        if (active) setList(x);
      })
      .catch(() => {
        if (active)
          setError(
            "Place search is unavailable. You can still choose a map pin.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  return { list, error };
}
