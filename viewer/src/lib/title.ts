import { useEffect } from "react";

/** The site's default title, in index.html too. */
export const SITE_TITLE = "C2A: Context2Agent Benchmark for AI Customer Support Agents";

/** Set the tab title while a page is shown (the pre-rendered pages already carry theirs); other pages get the site title back. */
export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = title;
    return () => { document.title = SITE_TITLE; };
  }, [title]);
}
