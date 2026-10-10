export function initForecastDetails() {
  const probabilities = [
    ...document.querySelectorAll<HTMLButtonElement>(".probability"),
  ];
  probabilities.forEach((button) =>
    button.addEventListener("click", () => {
      const opening = button.getAttribute("aria-expanded") !== "true";
      probabilities.forEach((item) => {
        const expanded = item === button && opening;
        item.setAttribute("aria-expanded", String(expanded));
        document.getElementById(item.getAttribute("aria-controls")!)!.hidden =
          !expanded;
      });
    }),
  );
}
