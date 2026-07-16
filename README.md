# blind-ab-eval

A Claude Code skill: build and deploy a blind A/B image-comparison evaluation
site from a CSV — GitHub Pages frontend + Google Sheet backend via Apps
Script. See [SKILL.md](SKILL.md) for the full workflow, architecture notes,
and usage.

## Install

Copy this folder into your Claude Code skills directory:

```bash
git clone https://github.com/<owner>/blind-ab-eval.git ~/.claude/skills/blind-ab-eval
```

Then invoke it from a Claude Code session (e.g. "use the blind-ab-eval skill
to build an evaluation page from this CSV").

## What it builds

- A static, no-login evaluation page (hosted on GitHub Pages) where
  evaluators compare two generated-image options per row in randomized,
  never-revealed left/right order.
- A Google Apps Script + Google Sheet backend that every vote, remark, and
  quality-review selection auto-saves to in real time.
- Per-option Fail / Pass / High Quality scoring with a multi-select reason
  checklist (default taxonomy covers face identity, body proportion,
  background quality, and more — fully customizable).
