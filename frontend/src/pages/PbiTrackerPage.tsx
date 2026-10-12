import type { PbiStage } from "../types";
import { PBIS } from "./pbis";

const STAGE_LABELS: Record<PbiStage, string> = {
  mvp: "Stage 1 — MVP (the useful tool)",
  engineering: "Stage 2 — Production engineering",
  search: "Stage 3 — Search & ranking",
};

const STAGE_ORDER: PbiStage[] = ["mvp", "engineering", "search"];

export function PbiTrackerPage() {
  return (
    <main className="max-w-4xl mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold mb-2">PBI Tracker</h1>
      <p className="text-slate-600 mb-8">
        Build roadmap for the Job Search Intelligence Platform. Backend-first.
      </p>

      {STAGE_ORDER.map((stage) => (
        <section key={stage} className="mb-8">
          <h2 className="text-xl font-semibold mb-4 border-b border-slate-200 pb-2">
            {STAGE_LABELS[stage]}
          </h2>
          <ul className="space-y-3">
            {PBIS.filter((pbi) => pbi.stage === stage).map((pbi) => (
              <li key={pbi.id} className="flex gap-3">
                <span className="mt-0.5 text-slate-400">☐</span>
                <div>
                  <span className="text-slate-500 text-sm">PBI {pbi.id}</span>
                  <br />
                  <span className="font-medium">{pbi.title}</span>
                  <p className="text-slate-600 text-sm">{pbi.description}</p>
                  {pbi.depends_on.length > 0 && (
                    <p className="text-slate-400 text-xs mt-0.5">
                      depends on PBI {pbi.depends_on.join(", ")}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
