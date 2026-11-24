import { useParams, useSearchParams } from "react-router";

/** The :job route param (a run key). */
export function useJob() {
  return useParams().job ?? "";
}

/** The URL query as a plain object, like Next's searchParams. */
export function useQuery(): Record<string, string | undefined> {
  const [params] = useSearchParams();
  return Object.fromEntries(params);
}

/** The live URL query, for event handlers that run outside render (the router has already updated window.location). */
export function currentSearchParams() {
  return new URLSearchParams(window.location.search);
}

export function useSetQuery() {
  const [, setParams] = useSearchParams();
  return (key: string, value: string) => {
    const next = currentSearchParams();
    next.set(key, value);
    setParams(next, { replace: true, preventScrollReset: true });
  };
}
