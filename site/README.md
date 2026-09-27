# Swag Bot site

Landing page for [Swag Bot](https://github.com/vishnu-Swagan/swag-bot). It lives in this folder so Vercel can use `site/` as the project root.

## Vercel

- Framework preset: **Next.js**
- Root directory: **`site`**
- Build command: **`npm run build`** (the Next.js default, `next build`, is the same)
- Install command: **`npm ci`**
- Output directory: leave empty. Next.js sets this.
- Node.js version: **22.x**

Set `NEXT_PUBLIC_SITE_URL` to the public origin, for example `https://swag.example`, so canonical and Open Graph URLs match the domain. If it is unset, the site uses the Vercel production host, then the deployment host.

## Install command

`INSTALL_COMMAND` in `lib/content.ts` is the one-line install. Change it to `pip install swag-bot` when PyPI publishing is on.

## Recorded demo

Put a file at `public/demo/demo.mp4` or `public/demo/demo.gif`. The demo section plays it. Until one of those files exists, the section shows a placeholder and does not fake a recording.
