---
name: blind-ab-eval
description: Build and deploy a blind A/B image-comparison evaluation site from a CSV — GitHub Pages frontend + Google Sheet backend via Apps Script. Each row shows a user photo, product photo, template/reference image, and two generated-image options in randomized (never-revealed) left/right order. Evaluators pick A好/B好/都好/都不好, leave an optional remark, and rate each option Fail/Pass/High Quality with a multi-select reason checklist. Every action auto-saves to Google Sheets in real time, works for evaluators with no Google account (no corporate-Workspace blocking), and supports many simultaneous evaluators. Trigger keywords: 盲测评测, blind eval, A/B对比评测, GSB评分, 生成图评测, model comparison eval, image quality review.
---

# Blind A/B Eval (GitHub Pages + Google Sheet)

Turns a CSV of two competing image-generation results into a shareable, no-login blind evaluation site. Built and battle-tested across a real multi-round session — see "Why this architecture" below for the failure modes it avoids.

## What you get

- **Static page on GitHub Pages** — any evaluator can open the link, no Google account needed, no corporate Workspace policy can block it (this is the #1 failure mode of Apps-Script-hosted pages, see below).
- **Backend on Google Apps Script** — a pure JSON API (no HTML serving) bound to a Google Sheet. Every vote/remark/quality-review POSTs there and upserts a row keyed by `(evaluator, row_index)`.
- **Per row**: small header thumbnails (user photo + product photo) next to the row title, then template image + option A + option B side by side, each option showing its raw image URL as a clickable link.
- **Blind by design**: options are randomly shuffled at generation time and the real identity is *never* sent to the client in a way that could leak — even after voting, the UI only ever shows "选项 A" / "选项 B", not which model they were. Only the Google Sheet (via `A_model`/`B_model` columns) knows the mapping.
- **Scoring per row**: A好 / B好 / 都好 / 都不好, plus a free-text remark box.
- **Scoring per option**: Fail / Pass / High Quality. Fail and Pass each unlock a scrollable multi-select checklist of specific reason codes (see `scripts/build_report.py` for the default taxonomy — face identity, body proportion, background quality, etc.). Selections are stored in the Sheet as full label text, not just codes.
- **A row only counts as done once everything is filled in**: GSB choice set, AND both A and B have a quality status, AND any status other than High Quality has at least one reason picked. The submit button only unlocks (with `--require-all-rows`) once every row meets this bar — not just once a GSB choice exists.
- **Row filters** (position-based, so they never leak which side is which): only-GSB-empty, only-quality-incomplete, only-missing-reason, plus an A-status and B-status dropdown (Fail/Pass/High Quality/empty) — lets an evaluator jump straight to what they haven't finished instead of scrolling all 100 rows.
- **Completion flow**: a sticky bottom bar tracks progress and unlocks a final "submit" button once the evaluator has covered every row (or immediately, in test mode), which logs a `completions` row and shows a thank-you screen. The hint text under the button also lists exactly which row numbers are still incomplete, each a clickable link that smooth-scrolls to that row — and if they click submit anyway while rows are missing (only possible in test mode, since the button is disabled otherwise), a confirm dialog spells out the same list before letting them proceed.
- **Live results dashboard** (`results.html`, Phase 5) — a separate, unlisted page for whoever runs the eval (not the evaluators) that reads straight from the Sheet and shows: a multi-select evaluator filter (checkboxes, select none = everyone), an always-visible per-evaluator progress module (rows tagged / completed / progress bar / whether they've hit submit), per-model Fail/Pass/High Quality counts and rates, GSB win counts, and Fail/Pass-reason breakdowns.

## Why this architecture (read before deploying differently)

Two failure modes were discovered the hard way and are why the design looks like this:

1. **Do not serve the evaluation page from Apps Script's `HtmlService`.** It seems natural to just deploy one Apps Script web app that both serves the page and receives votes. It does not work reliably for real evaluators: (a) if the Apps Script project's `Index.html` file is even slightly misconfigured, Apps Script throws "No HTML file named Index was found"; (b) more importantly, corporate Google Workspace accounts frequently get a generic Google Drive error — "Sorry, unable to open the file at present" — when navigating to a web app owned by a personal/external account, even with the deployment access set to "Anyone." This is a Workspace-level navigation policy, not something the deployment settings can fix. **The fix that actually works**: host the page as a static file (GitHub Pages) and have it POST/GET to the Apps Script URL via `fetch()`. Cross-origin `fetch()` to an Apps Script "Anyone" web app is not subject to the same navigation-blocking policy — verified working from an unauthenticated browser context with zero Google login.
2. **Apps Script deployments need an explicit new version to pick up code changes.** Editing `Code.gs`/pushing via clasp is not enough — the `/exec` URL only serves whatever was live at the last `deploy`. Always redeploy (`clasp deploy -i <deploymentId>`) after every backend change, and hard-refresh (or use an incognito window) when checking the frontend, since GitHub Pages + browser caching can serve a stale copy for a few minutes after a push.

## Phase 0 — Gather input

Ask the user for (or infer from context):
- CSV path.
- Which two columns hold the competing image URLs to compare, and short internal labels for each (these labels are stored in the Sheet, never shown to evaluators — e.g. version dates, model names).
- Whether they already have a Google Sheet + Apps Script backend from a previous run of this skill (reuse the same `--exec-url`) or need a new one (Phase 2).
- Their GitHub account — `gh auth status` to confirm `gh` is authenticated before creating a repo.

Column-mapping flags all have sensible defaults matching common Shopee AIGC try-on CSV exports (`user_image_url`, `images`, `global_be_category`, `item_id`, `aigc_generated_image_id` + `https://mms.img.susercontent.com/` prefix for the template image). Override any of them — see `python3 scripts/build_report.py --help`. If the CSV uses a fully different schema, just pass the matching `--*-col` flags.

## Phase 1 — Set up the Google Sheet + Apps Script backend (skip if reusing one)

1. Create a new Google Sheet (any name) under the account that will own the deployment — use their **personal** Google account if evaluators may be on a different corporate domain, since a same-domain Workspace account deploying "Anyone within domain" is fine but a personal-account deployment must use "Anyone" (`ANYONE_ANONYMOUS`) to be reachable at all — see the architecture note above.
2. In the Sheet: `Extensions → Apps Script`. This creates a container-bound script project.
3. Copy `assets/Code.gs` into the project's `Code.gs` (or your default `代码.js` if the UI is in Chinese), replacing the boilerplate.
4. Copy `assets/appsscript.json` into the project's manifest (Project Settings → check "Show appsscript.json" if it's hidden, or use `clasp` — see below).
5. Deploy: **Deploy → New deployment → type: Web app**. Execute as: **Me**. Who has access: **Anyone** (personal account) or **Anyone within [domain]** (Workspace account, only if evaluators are all in that same domain). Authorize the requested scopes when prompted.
6. Save the resulting `/exec` URL — this is `--exec-url` for Phase 3, and the value evaluators' browsers will `fetch()` against.

**Prefer `clasp` over manual copy-paste if available** (`npm install -g @google/clasp`, then `clasp login`, `clasp create --type sheets --title "..."` to create the Sheet+script together, `clasp push`, `clasp deploy`). This avoids the "paste didn't save" and "forgot to create Index.html" classes of bugs entirely, and lets you push future edits with one command instead of manual copy-paste. If you use clasp, you don't need an `Index.html` file at all — this skill's Code.gs has no `doGet` HTML-serving path by design.

## Phase 2 — Generate the report HTML

```bash
python3 scripts/build_report.py \
  --csv /path/to/data.csv \
  --exec-url "https://script.google.com/macros/s/XXXX/exec" \
  --option1-col gen_url_v1 --option1-label "v1_description" \
  --option2-col gen_url_v2 --option2-label "v2_description" \
  --title "项目名称 模型版本盲测评分" \
  --output index.html
```

Leave off `--require-all-rows` while testing — the submit button unlocks immediately so you can verify the flow without clicking through every row. Add it back for the real link:

```bash
python3 scripts/build_report.py ... --require-all-rows --output index.html
```

Always regenerate `index.html` (don't hand-edit it) if you need to change columns, labels, or the reason taxonomy — edit `scripts/build_report.py`'s `DEFAULT_FAIL_REASONS` / `DEFAULT_NOT_HQ_REASONS` lists or pass different `--*-col` flags, then rerun.

## Phase 3 — Push to GitHub Pages

```bash
mkdir my-eval-repo && cd my-eval-repo
cp /path/to/index.html .
git init && git add index.html
git commit -m "Blind A/B eval page"
gh repo create <repo-name> --public --source=. --remote=origin --push
gh api -X POST repos/<owner>/<repo-name>/pages -f "source[branch]=main" -f "source[path]=/"
```

The public repo is required for free GitHub Pages — the content itself (product/model images, a voting UI) isn't sensitive, but confirm with the user before creating a public repo if the CSV data might be.

Poll for the first build before sharing the link:
```bash
gh api repos/<owner>/<repo-name>/pages/builds/latest --jq .status   # wait for "built"
```

The live URL is `https://<owner>.github.io/<repo-name>/`.

## Phase 4 — Verify before sending to real evaluators

1. Open the URL in a fresh/incognito context (avoids stale-cache false negatives).
2. Enter a test name, cast a vote, mark an option Fail and pick 2+ reasons, add a remark.
3. Confirm the "已保存 ✓" status appears after each action.
4. Cross-check the write landed, using the backend directly (works from anywhere, no auth):
   ```
   fetch('<exec-url>?action=getMyVotes&evaluator=<test-name>').then(r=>r.text())
   ```
   Should return `{"ok":true,"votes":{"0":"<choice>"}}`.
5. Open the Sheet and confirm the row has sensible values, especially that `A_quality_reason`/`B_quality_reason` show full text (not bare codes like "1.1").
6. Delete the test evaluator's row(s) from both the `votes` and `completions` sheets before distributing the link.
7. If you added new columns to `Code.gs` (e.g. customized the payload), also delete the **header row** so it regenerates with the new columns on the next real submission — `getSheet_()` only writes headers when the sheet is completely empty.
8. Only now add `--require-all-rows` and regenerate/redeploy the final `index.html`.

## Phase 5 — Results dashboard (optional, for whoever runs the eval)

`results.html` is a second static page, generated separately, that live-reads the Sheet via `?action=getAllVotes` — no need to re-export CSVs to check progress. It reveals real model identity, so **don't link to it from index.html and don't send the URL to evaluators.**

Two ways to run `scripts/build_results_page.py`, depending on whether the labels you stored in the Sheet (`--option1-label`/`--option2-label` back in Phase 2) are already the real, stable identity or not:

- **Labels are already real and don't vary row to row** (the common case): just point it at the same `--exec-url`, no extra flags needed. `A_model`/`B_model` as stored are used directly.
- **Labels are generic (`version1`/`version2`) because the real model varies per row** (e.g. the two options come from a source column that's itself already an A/B test, so which real model produced "option 1" changes row to row): pass `--row-model-map-csv` pointing at a CSV with a real-model-code column pair, plus `--model1-col`/`--model2-col`. It embeds a row_index-keyed map and resolves version1/version2 → real code client-side, the same two-hop logic as `scripts/translate_to_model_codes.py` (position → version1/version2 → real code), just done live in JS instead of offline in Python.

```bash
python3 scripts/build_results_page.py \
  --exec-url "https://script.google.com/macros/s/XXXX/exec" \
  --title "项目名称 结果看板" \
  --output results.html
  # add --row-model-map-csv/--model1-col/--model2-col only if needed, see above

cp results.html /path/to/my-eval-repo/
cd /path/to/my-eval-repo && git add results.html && git commit -m "Add results dashboard" && git push
```

It reads live on every page load (plus a manual "刷新数据" button) — no rebuild needed as new votes come in. Only rebuild/redeploy it if you change `--exec-url`, the title, or the row-model mapping.

## Files

- `scripts/build_report.py` — CSV → `index.html` generator (the evaluator-facing page). Run `--help` for all flags.
- `scripts/build_results_page.py` — → `results.html` generator (live results dashboard, for the eval owner only). Run `--help` for all flags.
- `scripts/translate_to_model_codes.py` / `translate_full.py` / `analyze_gsb.py` — offline analysis helpers for post-hoc CSV exports from the Sheet; useful for one-off deep dives (fail-reason breakdowns, per-evaluator stats) beyond what the live dashboard shows. Run `--help` on each.
- `assets/Code.gs` — Apps Script backend (pure JSON API, no HTML serving — see architecture note). Exposes `getMyVotes` (single evaluator, used by index.html) and `getAllVotes`/`getAllCompletions` (everyone, used by results.html).
- `assets/appsscript.json` — manifest with `executeAs: USER_DEPLOYING`, `access: ANYONE_ANONYMOUS`.
