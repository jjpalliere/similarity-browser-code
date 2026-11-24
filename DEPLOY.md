# Deploy (Cloudflare Pages)

This repo is **not** deployed by the AEO Worker. It has its own **Pages** project: **`similarity-browser`** → `similarity-browser.pages.dev`.

## Git → Cloudflare

1. Cloudflare **Workers & Pages** → **similarity-browser** → **Settings** → **Pages configuration**.
2. Connect **`jjpalliere/Similarity-Browser`**: https://github.com/jjpalliere/Similarity-Browser
3. **Root directory:** `frontend`
4. **Build command:** `npm run build` (or `npm ci && npm run build`)
5. **Output directory:** `dist`
6. **Deploy command:** **`npm run deploy:pages`** (runs after build; **do not** use `npx wrangler versions upload`). If logs still show `versions upload`, the dashboard field was not saved.

7. **Version command:** leave **empty** / **None** if the UI offers it (don’t run `versions upload` there either).

Pushes to your production branch trigger deploys. You do not need `npm run deploy` from your laptop for routine updates.

## AEO integration

The **AEO** app (`terrain.run`) embeds this site in an iframe. See the AEO repo's `docs/DEPLOY_GIT.md` (private) for the two-repo picture (AEO Worker + this Pages repo).

## Manual deploy (fallback)

```bash
cd frontend
npm run build
npx wrangler pages deploy dist --project-name=similarity-browser
```
