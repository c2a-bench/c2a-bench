import { StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router";
import { TipRoot } from "@/components/charts";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NotFound } from "@/pages/not-found";
import { FIRST_POST } from "@/blog/first";
import { TopLoader } from "@/components/top-loader";
import { SectionScroll } from "@/components/section-scroll";
import { prefetchRun } from "@/lib/data";
import "@fontsource-variable/newsreader";
import "./fonts.css";
import "./globals.css";

import { AcquisitionPage, ArchitecturePage, BehaviorPage, Blog, BuildPage, CodePage, Home, JobLayout, OverviewPage, preloadPage, ResearchLayout, Rq1Page, Rq5Page, TaskRuns, TicketsPage } from "@/lib/pages";

/** Old run links: /runs/<job>/<rest> → /runs/<job>/research[/<rest>]. */
function ToResearch({ rest = "" }: { rest?: string }) {
  const { job } = useParams();
  return <Navigate to={`/runs/${job}/research${rest && `/${rest}`}`} replace />;
}

/** Old /cases links: the test case view of the tickets page. */
function ToCases() {
  const { job } = useParams();
  return <Navigate to={`/runs/${job}/tickets?view=case`} replace />;
}

/** The page-wide tooltip layer, cleared on every navigation. */
function PageTips() {
  return <TipRoot key={useLocation().key} />;
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/blog" element={<Navigate to={`/blog/${FIRST_POST}`} replace />} />
      <Route path="/blog/:slug" element={<Blog />} />
      <Route path="/t/:task" element={<TaskRuns />} />
      <Route path="/runs/:job" element={<JobLayout />}>
        <Route index element={<ToResearch />} />
        <Route path="overview" element={<ToResearch />} />
        {["acquisition", "architecture", "behavior", "evolution"].map((p) => (
          <Route key={p} path={p} element={<ToResearch rest={p} />} />
        ))}
        <Route path="research" element={<ResearchLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="rq1" element={<Rq1Page />} />
          <Route path="rq5" element={<Rq5Page />} />
          <Route path="acquisition" element={<AcquisitionPage />} />
          <Route path="architecture" element={<ArchitecturePage />} />
          <Route path="behavior" element={<BehaviorPage />} />
          <Route path="evolution" element={<Navigate to="../rq1" relative="path" replace />} />
        </Route>
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="code" element={<CodePage />} />
        <Route path="build" element={<BuildPage />} />
        <Route path="cases" element={<ToCases />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

/** Hovering or focusing a link to a run starts loading it (after 80 ms, so moving the mouse across a list does not). */
let hoverTimer: ReturnType<typeof setTimeout> | undefined;
const runOf = (t: EventTarget | null) => (t instanceof Element ? t.closest("a[href*='/runs/']")?.getAttribute("href")?.match(/\/runs\/([\w.-]+)\/?(\w*)/) : null);
document.addEventListener("pointerover", (e) => { clearTimeout(hoverTimer); const m = runOf(e.target); if (m) hoverTimer = setTimeout(() => prefetchRun(m[1], m[2]), 80); });
document.addEventListener("focusin", (e) => { const m = runOf(e.target); if (m) prefetchRun(m[1], m[2]); });

// The home page and the blog link to each other: once the first page is shown, fetch the other's code too.
setTimeout(() => { preloadPage("home"); preloadPage("blog"); }, 1500);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
      <SectionScroll />
      <TooltipProvider>
        <Suspense fallback={null}>
          <App />
        </Suspense>
        <PageTips />
        <TopLoader />
      </TooltipProvider>
    </BrowserRouter>
  </StrictMode>,
);
