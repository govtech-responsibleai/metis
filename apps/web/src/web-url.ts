// A link that the app may open: only an http or https URL, never a javascript: one.
export function webUrl(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}
