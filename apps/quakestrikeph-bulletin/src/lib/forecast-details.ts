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
  const tabs = [...document.querySelectorAll<HTMLButtonElement>(".tab")];
  const indicator = document.querySelector<HTMLElement>(".tab-indicator");
  const tablist = document.querySelector<HTMLElement>(".tablist");
  const align = () => {
    const selected = tabs.find(
      (tab) => tab.getAttribute("aria-selected") === "true",
    );
    if (!selected || !indicator) return;
    indicator.style.width = `${selected.offsetWidth}px`;
    indicator.style.transform = `translateX(${selected.offsetLeft}px)`;
  };
  const select = (tab: HTMLButtonElement) => {
    tabs.forEach((item) => {
      const selected = item === tab;
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected ? 0 : -1;
      document.getElementById(item.getAttribute("aria-controls")!)!.hidden =
        !selected;
    });
    if (tablist) {
      const left = tab.offsetLeft,
        right = left + tab.offsetWidth;
      if (left < tablist.scrollLeft) tablist.scrollLeft = left;
      else if (right > tablist.scrollLeft + tablist.clientWidth)
        tablist.scrollLeft = right - tablist.clientWidth;
    }
    align();
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (event) => {
      const next =
        event.key === "ArrowRight"
          ? (index + 1) % tabs.length
          : event.key === "ArrowLeft"
            ? (index + tabs.length - 1) % tabs.length
            : event.key === "Home"
              ? 0
              : event.key === "End"
                ? tabs.length - 1
                : null;
      if (next === null) return;
      event.preventDefault();
      select(tabs[next]);
      tabs[next].focus();
    });
  });
  if (tablist) new ResizeObserver(align).observe(tablist);
  align();
  const rangeCopy: Record<string, string> = {
    "Lower estimate":
      "This is the lower estimate of the largest magnitude if qualifying activity occurs. It is not a minimum guaranteed magnitude.",
    "Middle estimate":
      "The middle estimate sits between the lower and upper estimates. The actual largest magnitude may differ.",
    "Upper estimate":
      "This is the upper estimate of the largest magnitude if qualifying activity occurs. A larger earthquake remains possible.",
  };
  const choices = [
    ...document.querySelectorAll<HTMLButtonElement>(".range-choice"),
  ];
  choices.forEach((button) =>
    button.addEventListener("click", () => {
      choices.forEach((item) =>
        item.setAttribute("aria-pressed", String(item === button)),
      );
      document.getElementById("range-reading-title")!.textContent =
        button.dataset.rangeLabel!;
      document.getElementById("range-reading-copy")!.textContent =
        rangeCopy[button.dataset.rangeLabel!];
    }),
  );
  const links = [
    ...document.querySelectorAll<HTMLAnchorElement>(".navigation a"),
  ];
  const updateSection = () => {
    const visible = links.filter((link) => link.getClientRects().length > 0);
    let active: HTMLAnchorElement | undefined = visible[0];
    visible.forEach((link) => {
      if (
        (document.querySelector(link.hash)?.getBoundingClientRect().top ??
          Infinity) <= 84
      )
        active = link;
    });
    if (
      window.scrollY + window.innerHeight >=
      document.documentElement.scrollHeight - 2
    )
      active = visible.at(-1);
    links.forEach((link) => {
      if (link === active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  };
  let queued = false;
  window.addEventListener(
    "scroll",
    () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        updateSection();
      });
    },
    { passive: true },
  );
  window.addEventListener("resize", updateSection);
  updateSection();
}
