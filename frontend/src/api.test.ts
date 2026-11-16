import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchJob, fetchJobs, NotFoundError } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 404 ? "Not Found" : "OK",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchJobs", () => {
  it("builds the URL from defined, non-empty query fields only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs({ q: "engineer", company: "Google", location: "", source: undefined });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("location");
    expect(url).not.toContain("source");
    expect(url).toContain("q=engineer");
    expect(url).toContain("company=Google");
  });

  it("includes offset when it is a defined number", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs({ offset: 100 });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("offset=100");
  });

  it("omits offset when it is undefined", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchJobs({});

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("offset");
  });

  it("returns the parsed JobList", async () => {
    const payload = { items: [{ id: 1, title: "Engineer" }], total: 1 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(payload)));

    const result = await fetchJobs({ q: "engineer" });

    expect(result).toEqual(payload);
  });
});

describe("fetchJob", () => {
  it("fetches /jobs/{id} and returns the Job", async () => {
    const job = { id: 42, title: "Engineer" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(job));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchJob(42);

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/jobs/42"));
    expect(result).toEqual(job);
  });

  it("rethrows a 404 as NotFoundError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 404)));

    await expect(fetchJob(999)).rejects.toBeInstanceOf(NotFoundError);
  });
});
