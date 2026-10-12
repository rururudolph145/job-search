import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PbiTrackerPage } from "./PbiTrackerPage";
import { PBIS } from "./pbis";

describe("PbiTrackerPage", () => {
  it("renders every PBI title", () => {
    render(
      <MemoryRouter>
        <PbiTrackerPage />
      </MemoryRouter>,
    );
    for (const pbi of PBIS) {
      expect(screen.getByText(pbi.title)).toBeInTheDocument();
    }
  });
});
