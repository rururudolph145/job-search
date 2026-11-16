const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function isValidIsoDate(iso: string | null): boolean {
  if (iso === null) return false;
  const t = Date.parse(iso);
  return !Number.isNaN(t);
}

/**
 * Relative display of an ISO timestamp, or "—" when it is missing/invalid or
 * in the future (impossible for a job's "seen" timestamp). `now` is injected so
 * callers and tests control the reference instant; the absolute date is left to
 * the caller's `title` attribute.
 */
export function formatDate(iso: string | null, now: Date): string {
  if (!isValidIsoDate(iso)) return "—";
  const then = Date.parse(iso as string);
  const diff = now.getTime() - then;
  if (diff < 0) return "—";
  if (diff < MINUTE) return "Just now";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  return `${Math.floor(diff / DAY)} days ago`;
}
