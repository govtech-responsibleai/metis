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
