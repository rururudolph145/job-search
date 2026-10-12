export type PbiStage = "mvp" | "engineering" | "search";

export interface Pbi {
  id: string;
  stage: PbiStage;
  title: string;
  description: string;
  depends_on: string[];
}
