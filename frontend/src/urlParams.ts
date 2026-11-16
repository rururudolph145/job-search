const FILTER_KEYS = ["q", "company", "location", "source"] as const;

export interface SearchParams {
  q: string;
  company: string;
  location: string;
  source: string;
  page: number;
}

export function readSearchParams(searchParams: URLSearchParams): SearchParams {
  const rawPage = Number.parseInt(searchParams.get("page") ?? "", 10);
  const page = Number.isNaN(rawPage) || rawPage < 1 ? 1 : rawPage;

  return {
    q: searchParams.get("q") ?? "",
    company: searchParams.get("company") ?? "",
    location: searchParams.get("location") ?? "",
    source: searchParams.get("source") ?? "",
    page,
  };
}

export function filterActive(searchParams: URLSearchParams): boolean {
  return FILTER_KEYS.some((key) => (searchParams.get(key) ?? "").trim() !== "");
}

export function paramsToQueryString(searchParams: URLSearchParams): string {
  const s = searchParams.toString();
  return s ? `?${s}` : "";
}
