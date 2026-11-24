import introducingC2A from "./introducing-c2a.md?raw";
import { FIRST_POST } from "./first";

/**
 * The blog post (one; /blog redirects to the first). Its body is Markdown (GitHub flavour), rendered by pages/blog-post.tsx.
 * `description` is the search-result snippet (keep it to 160 characters); `updated` is the date of the last real edit, when there is one.
 */
export type Post = { slug: string; title: string; summary: string; description: string; date: string; updated?: string; body: string };

export const POSTS: Post[] = [
  {
    slug: FIRST_POST,
    title: "C2A: can agents keep up with a business that keeps changing?",
    summary:
      "668 test cases, seven builder models and six agent architectures: what happens when a builder turns a company's docs into a support agent, and then has to keep it up to date as the docs change.",
    description: "668 test cases, seven builder models and six agent architectures: what happens when coding agents build support agents and keep them current as docs change.",
    date: "2026-11-19",
    body: introducingC2A,
  },
];

export const postDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

/** Minutes to read a post: its words (Markdown marks, links' targets and figure markers left out) at 220 a minute. */
export const readMinutes = (body: string) => {
  const text = body
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[#*_`>~|-]/g, " ");
  const words = text.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w)).length;
  return Math.max(1, Math.round(words / 220));
};
