# Swag Bot site

Next.js site for [Swag Bot](https://github.com/vishnu-Swagan/swag-bot). Vercel should use root directory `site` and Node 22.

## Setup

```bash
cd site
npm ci
npm run dev
```

Set `NEXT_PUBLIC_SITE_URL` to the canonical origin (no trailing slash) in production. Metadata, the sitemap, and robots.txt use it. If it is unset, the build falls back to the Vercel URL, then `http://localhost:3000`.

```bash
npm run lint
npm run typecheck
npm run build
```

## Demo video

Put the recording at `public/demo/demo.mp4`. The home page uses `public/demo/poster.svg` until that file answers.

## What this site does not do

- No analytics script and no tracking cookies. Theme choice is `localStorage`.
- The GitHub star count is fetched in the browser from the GitHub API. If that fails, the button stays and the number is omitted.
- Legal pages are templates. Fields marked `[OWNER TO CONFIRM]` need a real entity name, contact email, and governing-law jurisdiction, plus a lawyer's review, before they should be treated as final.
- Social links labeled “placeholder” are not accounts.

## Claims

Product copy lives in `lib/site.ts` and `lib/docs.ts`. Keep it aligned with the repository and with facts the maintainer has confirmed. Do not add user counts, star snapshots, testimonials, or logos of other products.
