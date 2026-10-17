import { describe, expect, it } from "vitest";
import { formatDate, isValidIsoDate } from "./formatDate";

const NOW = new Date("2026-10-18T12:00:00.000Z");

function minutesAgo(mins: number): Date {
  return new Date(NOW.getTime() - mins * 60_000);
}

describe("formatDate", () => {
  it("renders an em-dash for null", () => {
    expect(formatDate(null, NOW)).toBe("—");
  });

  it("renders an em-dash for an invalid date", () => {
    expect(formatDate("not-a-date", NOW)).toBe("—");
  });

  it("renders an em-dash for an impossible (overflowing) date", () => {
    expect(formatDate("2026-99-99T00:00:00Z", NOW)).toBe("—");
  });

  it("renders 'Just now' for a very recent timestamp", () => {
    expect(formatDate(minutesAgo(0.5).toISOString(), NOW)).toContain("now");
  });

  it("renders a minutes-ago phrase under an hour", () => {
    expect(formatDate(minutesAgo(30).toISOString(), NOW)).toBe("30m ago");
  });

  it("renders an hours-ago phrase under a day", () => {
    expect(formatDate(minutesAgo(60 * 5).toISOString(), NOW)).toBe("5h ago");
  });

  it("renders a days-ago phrase at a day or more", () => {
    expect(formatDate(minutesAgo(60 * 24 * 3).toISOString(), NOW)).toBe("3 days ago");
  });
});

describe("isValidIsoDate", () => {
  it("accepts a valid ISO string and rejects garbage", () => {
    expect(isValidIsoDate("2026-10-18T12:00:00Z")).toBe(true);
    expect(isValidIsoDate(null)).toBe(false);
    expect(isValidIsoDate("x")).toBe(false);
  });
});
