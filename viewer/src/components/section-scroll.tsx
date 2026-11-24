import { useEffect } from "react";
import { useLocation } from "react-router";

/** Scroll to the section a URL names (`/#results`), once it has rendered. */
export function SectionScroll() {
  const { pathname, hash, key } = useLocation();
  useEffect(() => {
    if (!hash) return;
    let id: string;
    try { id = decodeURIComponent(hash.slice(1)); } catch { return; }
    let observer: MutationObserver | undefined;
    const scroll = () => {
      const element = document.getElementById(id);
      if (!element) return false;
      element.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      observer?.disconnect();
      return true;
    };
    if (scroll()) return;
    // Landing content may still be suspended while its catalog loads.
    observer = new MutationObserver(scroll);
    observer.observe(document.getElementById("root")!, { childList: true, subtree: true });
    const timeout = setTimeout(() => observer?.disconnect(), 10_000);
    return () => { clearTimeout(timeout); observer?.disconnect(); };
  }, [pathname, hash, key]);
  return null;
}
