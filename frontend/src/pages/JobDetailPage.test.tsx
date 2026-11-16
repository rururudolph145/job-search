import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { NotFoundError } from "../api";
import { makeJob } from "../test-utils";
import { JobDetailPage } from "./JobDetailPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/jobs/:id" element={<JobDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("JobDetailPage", () => {
  it("renders every field including external job ID", async () => {
    const job = makeJob({ id: 42, external_job_id: "EXT-42", company: "Google", location: "Tokyo" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => job,
    } as Response));

    renderAt("/jobs/42");

    expect(await screen.findByRole("heading", { name: "Software Engineer" })).toBeInTheDocument();
    expect(screen.getByText("Google")).toBeInTheDocument();
    // "Tokyo" renders twice once city is shown: the display location and the
    // structured city. Pin the location row, then the city and country rows.
    expect(screen.getByText("Location").nextElementSibling).toHaveTextContent("Tokyo");
    expect(screen.getByText("City").nextElementSibling).toHaveTextContent("Tokyo");
    expect(screen.getByText("Country").nextElementSibling).toHaveTextContent("JP");
    expect(screen.getByText("google_careers")).toBeInTheDocument();
    expect(screen.getByText("EXT-42")).toBeInTheDocument();
  });

  it("renders an em-dash for null company, location, city and country", async () => {
    const job = makeJob({
      company: null,
      location: null,
      city: null,
      country: null,
      external_job_id: null,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => job,
    } as Response));

    renderAt("/jobs/42");
    await screen.findByRole("heading", { name: "Software Engineer" });

    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3); // company, location, external_job_id
    expect(dashes.length).toBeGreaterThanOrEqual(5); // + city, country
  });

  it("shows 'Job not found.' without a Retry button on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new NotFoundError("Not Found")));

    renderAt("/jobs/999999");

    expect(await screen.findByText("Job not found.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /jobs/i })).toBeInTheDocument();
  });

  it("shows Retry on a non-404 error", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => makeJob() } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/jobs/42");

    expect(await screen.findByText("Couldn't load this job.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Software Engineer" })).toBeInTheDocument();
  });

  it("renders not-found without fetching for a non-numeric id", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/jobs/abc");

    expect(await screen.findByText("Job not found.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves the list query string in the Back link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => makeJob({ id: 42 }),
    } as Response));

    renderAt("/jobs/42?q=engineer&page=2");

    const backLink = await screen.findByRole("link", { name: /Back/ });
    expect(backLink).toHaveAttribute("href", "/jobs?q=engineer&page=2");
  });

  it("links to bare /jobs when there is no query string", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => makeJob({ id: 42 }),
    } as Response));

    renderAt("/jobs/42");

    const backLink = await screen.findByRole("link", { name: /Back/ });
    expect(backLink).toHaveAttribute("href", "/jobs");
  });
});
