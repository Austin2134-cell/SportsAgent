export const meta = {
  name: 'spokeo-hr-staffing-prospecting-batch',
  description: 'Per-account batch: research a caller-supplied list of HR/Staffing companies, dedupe vs HubSpot, draft 4-touch outbound sequences for Spokeo',
  phases: [
    { title: 'Research & draft', detail: 'per-company contact research, HubSpot dedupe, 4-touch sequence drafting' },
  ],
}

// COMPLIANCE NOTE: this workflow does NOT run any broad/filtered ZoomInfo company
// search to auto-discover new accounts. ZoomInfo's own usage terms prohibit "mass
// data scraping or bulk extraction for database building" and "creating contact
// lists for cold outreach without legal basis" - an automated daily discovery loop
// filtered for "outbound prospecting targets" is exactly that. Instead, the caller
// (Austin) supplies the target company names - from his own account list, LinkedIn
// Sales Nav, referrals, inbound signals, etc. - and this workflow does individual,
// per-account research and drafting for those named accounts only. That matches
// ZoomInfo's stated allowed use: "individual research queries, not mass data
// harvesting."

const companyNames = (args && args.companyNames) || []
const batchSize = (args && args.batchSize) || 20
const excludeCompanyIds = new Set((args && args.excludeCompanyIds) || [])
const excludeEmails = new Set(((args && args.excludeEmails) || []).map(e => String(e).toLowerCase()))

if (!companyNames.length) {
  throw new Error('companyNames is required - supply the specific target company names to research. This workflow does not auto-discover accounts.')
}

const targets = companyNames.slice(0, batchSize)
if (companyNames.length > targets.length) {
  log(`${companyNames.length - targets.length} company names beyond the ${batchSize}-per-run cap were not processed this run.`)
}

const BATCH_SCHEMA = {
  type: 'object',
  properties: {
    records: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          skip: { type: 'boolean' },
          skipReason: { type: 'string' },
          companyName: { type: 'string' },
          companyWebsite: { type: 'string' },
          contactName: { type: 'string' },
          contactTitle: { type: 'string' },
          email: { type: 'string' },
          phone: { type: 'string' },
          linkedin: { type: 'string' },
          hook: { type: 'string' },
          sequence: {
            type: 'object',
            properties: {
              initialSubject: { type: 'string' },
              initialBody: { type: 'string' },
              followup1Body: { type: 'string' },
              followup2Body: { type: 'string' },
              followup3Body: { type: 'string' },
            },
          },
        },
        required: ['skip'],
      },
    },
  },
  required: ['records'],
}

function chunk(arr, size) {
  const out = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}
const groups = chunk(targets, 5)

phase('Research & draft')
function batchPromptFor(group) {
  return `You are doing individual, per-account B2B sales prospecting research for Spokeo (identity verification, people search, and contact/address history API) targeting HR & Staffing companies as buyers who need to verify the identity of candidates, temp workers, or gig/marketplace providers quickly and accurately during hiring or onboarding.

These are SPECIFIC, named target companies supplied by the requester (not a discovered list) - research exactly these ${group.length} companies, one at a time, as individual lookups:
${group.map(n => `- ${n}`).join('\n')}

For each company:
1. Use the ZoomInfo search_companies_v2 or search_companies tool with the companyName field set to this exact company name to find its ZoomInfo companyId. This is a single, targeted, name-based lookup for one specific company - not a filtered/bulk discovery search. If no confident match is found, set skip: true, skipReason: "company not found in ZoomInfo".
2. Use the ZoomInfo search_contacts_v2 tool with companyIdList: [companyId], managementLevelList: ["VP Level Exec","Director","C Level Exec"], departmentList including Operations, Human Resources, or similar. Look for a real decision-influencer: VP/Director of Operations, Talent Acquisition/Recruiting, Trust & Safety, Compliance, or similar. Prefer a result where hasEmail is true.
3. Use ZoomInfo enrich_contacts (by personId) to get their verified email, phone, and LinkedIn URL, and confirm job title/company.
4. Use ZoomInfo enrich_company_signals for this one company to find one concrete, current hook for a cold email opener: a funding round, product launch, leadership move, hiring surge, or press mention. If nothing useful comes back, fall back to a role-based hook about identity verification at hiring speed/scale for that specific role.
5. Check whether this contact or company already exists in HubSpot using the HubSpot search_crm_objects or query_crm_data tool (search by email and by company name). If they already exist as a contact or associated company in the CRM, do NOT draft outreach - set skip: true, skipReason: "already in HubSpot CRM".
6. If you cannot find any qualifying VP/Director/C-level contact with a usable email in Operations, HR, Recruiting, Trust & Safety, or Compliance, set skip: true, skipReason: "no qualified contact found".
7. Otherwise, draft a 4-touch outbound sequence for this contact, following these strict rules:
   - No em dashes. Never write "I hope this email finds you well," "touching base," "circling back," "synergy," "leverage" as a verb, or "solutions."
   - Short paragraphs, 2-3 sentences max per paragraph. Active voice. Conversational, not templated-sounding. No bullet lists inside the emails.
   - Initial email: opening line is the specific hook (not a generic compliment), next 1-2 sentences state the pain the hook implies, then one sentence on how Spokeo's identity verification / people data API addresses it (no product dump), then ONE low-friction call to action (e.g. "worth a 15-minute conversation?" rather than "can we get on a call?").
   - Follow-up 1 (send ~day 3-5): one sentence, bump the thread, don't re-explain anything.
   - Follow-up 2 (send ~day 8-10): 2-3 sentences, add a new angle, data point, or different framing of the problem.
   - Follow-up 3 (send ~day 15-20): the graceful breakup email; acknowledge they may not be interested, leave the door open, gracious tone.
   - Provide a subject line only for the initial email.

Return exactly one record per company in the group, in the same order the companies were listed, even for the ones you skip. Do not fabricate contact details, emails, or companyIds if a real match isn't found - skip instead.`
}

const batchResults = await parallel(
  groups.map(group => () => agent(batchPromptFor(group), { phase: 'Research & draft', schema: BATCH_SCHEMA }))
)

const allRecords = batchResults.filter(Boolean).flatMap(r => r.records || [])
const usable = allRecords.filter(r => !r.skip && r.email && !excludeEmails.has(String(r.email).toLowerCase()))
const skipped = allRecords.filter(r => r.skip || !r.email)

log(`${usable.length} usable contacts drafted; ${skipped.length} skipped.`)

return {
  batch: usable,
  requestedCount: targets.length,
  skippedCount: skipped.length,
  skipReasons: skipped.map(s => ({ company: s.companyName, reason: s.skipReason })),
}
