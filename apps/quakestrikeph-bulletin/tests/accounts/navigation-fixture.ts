// The plain Vite fixture has no Astro router; Astro navigation tests use 4333.
export async function navigate(href: string) { location.assign(href); }
