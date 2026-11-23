import introducingC2A from "./introducing-c2a.md?raw";

/** The blog post (one; /blog shows the first). Its body is Markdown (GitHub flavour), rendered by pages/blog-post.tsx. */
export type Post = { slug: string; title: string; summary: string; date: string; body: string };

export const POSTS: Post[] = [
  {
    slug: "introducing-c2a",
    title: "C2A: can agents keep up with a business that keeps changing?",
    summary:
      "668 test cases, seven builder models and six agent architectures: what happens when a builder turns a company's docs into a support agent, and then has to keep it up to date as the docs change.",
    date: "2026-11-19",
    body: introducingC2A,
  },
];

export const postDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
