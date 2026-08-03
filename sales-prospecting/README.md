# Spokeo HR/Staffing Outbound Prospecting Automation

Automates the research + drafting side of Austin's outbound prospecting for Spokeo,
targeting HR & Staffing companies as buyers for Spokeo's identity verification /
people data API.

This does **not** send email. It has no write access to HubSpot and no email/sequencing
connector. Each run produces an Excel workbook of researched contacts with a full
4-touch sequence (initial + 3 follow-ups), formatted to scan and copy-paste quickly.

## Compliance: why this is per-account, not auto-discovery

The first version of this workflow auto-discovered ~40 new companies a day via a broad
ZoomInfo `search_companies_v2` filter (industry + employee range), specifically to build
a rolling cold-outreach list. **That's a real conflict with ZoomInfo's own usage terms**,
which prohibit "mass data scraping or bulk extraction for database building" and
"creating contact lists for cold outreach without legal basis," and say to "use results
for individual research queries, not mass data harvesting." An automated recurring
bulk-discovery loop filtered for prospecting targets is exactly that pattern.

`spokeo_hr_staffing_workflow.js` now takes a caller-supplied list of company names
(`args.companyNames`) — from Austin's own account list, LinkedIn Sales Nav, referrals,
inbound signals, etc. — and does individual, per-account ZoomInfo lookups (company
match by name, contact search, enrichment, signals) for those *named* accounts only.
No broad/filtered discovery search runs. This matches ZoomInfo's stated allowed use.

## Why files live here instead of the session scratchpad

The Claude Code Remote session's local disk (including `/tmp` scratchpad and any
`workflows/scripts/*.js` file a Workflow call writes) is **not durable** — it can be
wiped when the container is reclaimed between runs. Git is the only persistence layer
available to this session, so:

- `spokeo_hr_staffing_workflow.js` — the Workflow script source. Read fresh from the
  repo and passed to the `Workflow` tool via the `script` param (not `scriptPath`),
  since a local scriptPath from a prior run will not survive a container reset.
- `prospecting_log.csv` — dedup log. Every contact that's been drafted (whether or not
  it was actually sent) gets appended here with the date, so future runs exclude them.
  Committed and pushed after every run.

## How a run works

1. Austin supplies a list of target company names (the accounts he wants researched).
2. `git pull` this branch to get the latest log + script.
3. Parse `prospecting_log.csv` for already-contacted `company_id`s and `contact_email`s.
4. Run `spokeo_hr_staffing_workflow.js` via the `Workflow` tool (inline `script`, not
   `scriptPath`), passing `companyNames` (the supplied list), `excludeCompanyIds`,
   `excludeEmails`, and `batchSize` (cap per run, default 20).
5. The workflow does, per named company: find its ZoomInfo companyId by name match;
   find a qualified VP/Director/C-level contact in Operations, HR, Recruiting, Trust &
   Safety, or Compliance; enrich their verified email/phone/LinkedIn; check HubSpot CRM
   to skip anyone already in the pipeline; pull company news/intent/scoop signals for a
   personalization hook; and draft the 4-touch sequence per the `sales-prospecting`
   skill's style rules (no em dashes, no filler phrases, one CTA, short paragraphs).
6. Append the day's contacts to `prospecting_log.csv`, commit + push.
7. Build `spokeo_batch_YYYY-MM-DD.xlsx` (contact info + all 4 touches, one row per
   contact, wrapped text, frozen header) and send it to Austin via `SendUserFile`,
   noting how many companies were skipped and why.

## Adjusting

- **Target list**: pass a different `companyNames` array as `args` to the workflow.
- **Batch size**: change `batchSize` in the args passed to the workflow (default 20/run).
- **Sequence style**: edit the drafting rules embedded in `batchPromptFor()` in the
  workflow script.
- **Output format**: the `.xlsx` is built by the calling session with `openpyxl` after
  the workflow returns its JSON — not by the workflow script itself (it has no
  filesystem access).

## Known limitation

There is no automatic daily trigger for this version, since it requires Austin to
supply the target company list each time rather than running unattended. The prior
recurring 9am Mon-Fri Routine (`Spokeo HR/Staffing prospecting batch`) still exists but
points at the old auto-discovery design and should not be re-enabled as-is.
