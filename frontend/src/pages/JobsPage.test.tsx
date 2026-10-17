import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { JobList } from "../api";
import { makeJob } from "../test-utils";
import { JobsPage } from "./JobsPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderWithRouter(path = "/jobs") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <JobsPage />
    </MemoryRouter>,
  );
}

describe("JobsPage", () => {
  it("renders each job's title from the fetched list", async () => {
    const list: JobList = {
      items: [makeJob({ title: "Software Engineer" }), makeJob({ id: 2, title: "Data Analyst" })],
      total: 2,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    renderWithRouter();

    expect(await screen.findByText("Software Engineer")).toBeInTheDocument();
    expect(screen.getByText("Data Analyst")).toBeInTheDocument();
  });

  it("shows the loading state before the fetch resolves", async () => {
    let resolve!: (r: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((r) => { resolve = r; })));

    renderWithRouter();

    expect(screen.getByRole("status")).toHaveTextContent("Loading jobs…");
    resolve({ ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }) } as Response);
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument();
  });

  it("distinguishes empty-with-filters from empty-without-filters", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response));

    const { unmount } = renderWithRouter();
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument();
    unmount();

    renderWithRouter("/jobs?q=zzz");
    expect(await screen.findByText("No jobs match your filters.")).toBeInTheDocument();
  });

  it("shows Retry on error and re-fetches on click", async () => {
    const success: JobList = { items: [makeJob({ title: "Software Engineer" })], total: 1 };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, statusText: "Server Error", json: async () => ({}) } as Response)
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => success } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderWithRouter();

    expect(await screen.findByText("Couldn't load jobs.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Software Engineer")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("submits the form with all filters and a reset page", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderWithRouter();

    await userEvent.type(screen.getByLabelText("Title"), "engineer");
    await userEvent.type(screen.getByLabelText("Company"), "Google");
    await userEvent.type(screen.getByLabelText("Location"), "Tokyo");
    await userEvent.type(screen.getByLabelText("Source"), "google_careers");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    const url = fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0] as string;
    expect(url).toContain("q=engineer");
    expect(url).toContain("company=Google");
    expect(url).toContain("location=Tokyo");
    expect(url).toContain("source=google_careers");
    expect(url).toContain("offset=0");
  });

  it("clear filters resets all params", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderWithRouter("/jobs?q=engineer");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    const url = fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0] as string;
    expect(url).not.toContain("q=");
  });

  it("disables Prev on page 1 and Next on the last page", async () => {
    const list: JobList = { items: [makeJob()], total: 2 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    // First render: page 1 — Prev disabled.
    const { unmount } = renderWithRouter();
    await screen.findByText("Software Engineer");
    const prev1 = screen.getByRole("button", { name: "Prev" }) as HTMLButtonElement;
    expect(prev1.disabled).toBe(true);
    unmount();

    // Page 2 is the last of 2 — Next disabled.
    renderWithRouter("/jobs?page=2");
    await screen.findByText("Software Engineer");
    const next2 = screen.getByRole("button", { name: "Next" }) as HTMLButtonElement;
    expect(next2.disabled).toBe(true);
  });

  it("shows 'Showing X–Y of N' and 'Page P of T' from total", async () => {
    const list: JobList = {
      items: [makeJob({ id: 51 })],
      total: 101,
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    renderWithRouter("/jobs?page=2"); // offset = 50, items.length = 1

    await screen.findByText("Software Engineer");
    expect(screen.getByText("Showing 51–51 of 101")).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("a card links to /jobs/{id} preserving the current query string", async () => {
    const list: JobList = { items: [makeJob({ id: 42 })] , total: 1 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => list,
    } as Response));

    renderWithRouter("/jobs?q=engineer&page=2");

    const link = await screen.findByRole("link", { name: /Software Engineer/ });
    expect(link).toHaveAttribute("href", "/jobs/42?q=engineer&page=2");
  });

  it("hides the pager when total is 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => ({ items: [], total: 0 }),
    } as Response));

    renderWithRouter();
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument();
    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument();
  });
});
