import { describe, expect, it } from "vitest";
import {
  filterActive,
  paramsToQueryString,
  readSearchParams,
} from "./urlParams";

describe("readSearchParams", () => {
  it("maps a full set of params", () => {
    const p = new URLSearchParams("q=engineer&company=Google&location=Tokyo&source=gc&page=3");
    expect(readSearchParams(p)).toEqual({
      q: "engineer",
      company: "Google",
      location: "Tokyo",
      source: "gc",
      page: 3,
    });
  });

  it("defaults missing params", () => {
    const p = new URLSearchParams("");
    expect(readSearchParams(p)).toEqual({
      q: "",
      company: "",
      location: "",
      source: "",
      page: 1,
    });
  });

  it("clamps page to 1 when absent or invalid", () => {
    expect(readSearchParams(new URLSearchParams("")).page).toBe(1);
    expect(readSearchParams(new URLSearchParams("page=abc")).page).toBe(1);
    expect(readSearchParams(new URLSearchParams("page=0")).page).toBe(1);
    expect(readSearchParams(new URLSearchParams("page=-2")).page).toBe(1);
  });
});

describe("filterActive", () => {
  it("is false with no filters", () => {
    expect(filterActive(new URLSearchParams(""))).toBe(false);
  });

  it("is true when any recognized filter is non-empty", () => {
    expect(filterActive(new URLSearchParams("q=x"))).toBe(true);
    expect(filterActive(new URLSearchParams("company=x"))).toBe(true);
    expect(filterActive(new URLSearchParams("location=x"))).toBe(true);
    expect(filterActive(new URLSearchParams("source=x"))).toBe(true);
  });

  it("ignores the page param", () => {
    expect(filterActive(new URLSearchParams("page=3"))).toBe(false);
  });
});

describe("paramsToQueryString", () => {
  it("returns empty string for no params", () => {
    expect(paramsToQueryString(new URLSearchParams(""))).toBe("");
  });

  it("prefixes non-empty params with '?'", () => {
    expect(paramsToQueryString(new URLSearchParams("q=a&page=2"))).toBe("?q=a&page=2");
  });
});
