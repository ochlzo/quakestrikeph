export function initForecastDetails(root: Document | HTMLElement = document) {
  const probabilities = [
    ...root.querySelectorAll<HTMLButtonElement>(".probability"),
  ];
  const listeners = probabilities.map((button) => {
    function toggle() {
      const opening = button.getAttribute("aria-expanded") !== "true";
      probabilities.forEach((item) => {
        const expanded = item === button && opening;
        item.setAttribute("aria-expanded", String(expanded));
        const explanation = root.querySelector<HTMLElement>(`#${item.getAttribute("aria-controls")}`);
        if (explanation) explanation.hidden = !expanded;
      });
    }
    button.addEventListener("click", toggle);
    return () => button.removeEventListener("click", toggle);
  });
  return () => listeners.forEach((remove) => remove());
}
