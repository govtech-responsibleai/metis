// Timestamps in browser records use Unix epoch milliseconds, matching Date.now().
export function relativeTime(
  epochMilliseconds: number,
  now = Date.now(),
): string {
  const seconds = Math.max(0, (now - epochMilliseconds) / 1000);
  const minutes = seconds / 60;
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.floor(minutes)} min ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

const SAME_YEAR = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const OTHER_YEAR = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

// The local date and time to the second, with the year only when it is not the current year.
export function absoluteTime(
  epochMilliseconds: number,
  now = Date.now(),
): string {
  const date = new Date(epochMilliseconds);
  const format =
    date.getFullYear() === new Date(now).getFullYear() ? SAME_YEAR : OTHER_YEAR;
  return format.format(date);
}
