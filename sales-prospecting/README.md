# Spokeo HR/Staffing Outbound Prospecting Automation

Automates the research + drafting side of Austin's outbound prospecting for Spokeo,
targeting mid-market US HR & Staffing companies (100-2000 employees) as buyers for
Spokeo's identity verification / people data API.

This does **not** send email. It has no write access to HubSpot and no email/sequencing
connector. Each run produces a CSV of researched contacts with a full 4-touch sequence
(initial + 3 follow-ups) that gets copied into HubSpot Sales Sequences by hand.

## Why files live here instead of the session scratchpad

The Claude Code Remote session's local disk (including `/tmp` scratchpad and any
`workflows/scripts/*.js` file a Workflow call writes) is **not durable** — it can be
wiped when the container is reclaimed between runs, which reliably happens over a
multi-day gap like a Mon-Fri 9am schedule. Git is the only persistence layer available
to this session, so:

- `spokeo_hr_staffing_workflow.js` — the Workflow script source. The routine reads this
  file fresh from the repo each firing and passes its contents to the `Workflow` tool via
  the `script` param (not `scriptPath`), since a local scriptPath from a prior run will not
  survive a container reset.
- `prospecting_log.csv` — dedup log. Every contact that's been drafted (whether or not it
  was actually sent) gets appended here with the date, so future runs exclude them from
  ZoomInfo re-discovery. Committed and pushed after every run.

## How the daily run works (Routine `Spokeo HR/Staffing prospecting batch`)

Cron: `0 15 * * 1-5` UTC = weekdays 9am America/Denver (MDT). Fires into this same
persistent session (`session_01JxycWMEggEBgTzgbJn1gtE`).

Each firing:
1. `git pull` this branch to get the latest log + script.
2. Parse `prospecting_log.csv` for already-contacted `company_id`s and `contact_email`s.
3. Run `spokeo_hr_staffing_workflow.js` via the `Workflow` tool (inline `script`, not
   `scriptPath`), passing `excludeCompanyIds`, `excludeEmails`, `batchSize: 20`, and a
   `page` number that advances each run (ZoomInfo `search_companies_v2` pagination over
   the `HR & Staffing` industry / employee-range filter, sorted by name, so each run
   surfaces a fresh slice of ~4,400 matching companies).
4. The workflow does, per candidate company: find a qualified VP/Director/C-level
   contact in Operations, HR, Recruiting, Trust & Safety, or Compliance via ZoomInfo;
   enrich their verified email/phone/LinkedIn; check HubSpot CRM to skip anyone already
   in the pipeline; pull company news/intent/scoop signals for a personalization hook;
   and draft the 4-touch sequence per the `sales-prospecting` skill's style rules (no em
   dashes, no filler phrases, one CTA, short paragraphs).
5. Append the day's contacts to `prospecting_log.csv`, commit + push.
6. Write `spokeo_batch_YYYY-MM-DD.csv` (contact info + all 4 touches) and send it to
   Austin via `SendUserFile`, noting how many companies were skipped and why.

## Adjusting

- **Cadence / time**: `update_trigger` on trigger id (see `list_triggers`), or delete and
  recreate with `create_trigger`.
- **Vertical / filters**: edit the ZoomInfo `search_companies_v2` params in
  `spokeo_hr_staffing_workflow.js` (industry, employee range, etc.).
- **Batch size**: change `batchSize` in the args passed to the workflow (default 20/day).
- **Sequence style**: edit the drafting rules embedded in `batchPromptFor()` in the
  workflow script.

## Known limitation

The Routine trigger currently has no connector grants attached, so fired sessions may
not have `ZoomInfo`/`HubSpot` MCP tools available unless the trigger is recreated with
`connectors: ["ZoomInfo", "HubSpot"]`, or it resumes into a session (like this one) that
already holds those connectors itself.
