export const meta = {
  name: 'spokeo-hr-staffing-prospecting-batch',
  description: 'Daily batch: find mid-market HR/Staffing accounts, research contacts, dedupe vs HubSpot, draft 4-touch outbound sequences for Spokeo',
  phases: [
    { title: 'Discover accounts', detail: 'search ZoomInfo for new mid-market HR & Staffing companies' },
    { title: 'Research & draft', detail: 'per-company contact research, HubSpot dedupe, 4-touch sequence drafting' },
  ],
}

const page = (args && args.page) || 1
const poolSize = (args && args.poolSize) || 40
const batchSize = (args && args.batchSize) || 20
const excludeCompanyIds = new Set((args && args.excludeCompanyIds) || [])
const excludeEmails = new Set(((args && args.excludeEmails) || []).map(e => String(e).toLowerCase()))

const DISCOVERY_SCHEMA = {
  type: 'object',
  properties: {
    companies: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          companyId: { type: 'integer' },
          name: { type: 'string' },
          website: { type: 'string' },
          city: { type: 'string' },
          state: { type: 'string' },
          employeeCount: { type: 'integer' },
        },
        required: ['companyId', 'name'],
      },
    },
  },
  required: ['companies'],
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

phase('Discover accounts')
const discoveryPrompt = `Search ZoomInfo for mid-market US HR & Staffing companies as outbound prospecting targets for Spokeo, an identity verification / people data API company. Call the ZoomInfo search_companies_v2 tool with: industryList: ["HR & Staffing"], country: "United States", employeeRangeMin: 100, employeeRangeMax: 2000, businessModel: ["B2B"], sort: "name", page: ${page}, pageSize: ${poolSize}. Return the full page of results as structured data (companyId, name, website, city, state, employeeCount) without filtering or skipping any of them.`
const discovery = await agent(discoveryPrompt, { schema: DISCOVERY_SCHEMA, label: 'discover-accounts' })

const candidates = (discovery.companies || []).filter(c => !excludeCompanyIds.has(c.companyId))
log(`Discovered ${(discovery.companies || []).length} companies on page ${page}; ${candidates.length} are new (not previously targeted).`)

function chunk(arr, size) {
  const out = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}
const groups = chunk(candidates, 5)

phase('Research & draft')
function companyLine(c) {
  return `- ${c.name} (ZoomInfo companyId: ${c.companyId}, website: ${c.website || 'n/a'}, ${c.city || ''} ${c.state || ''}, ~${c.employeeCount || '?'} employees)`
}

function batchPromptFor(group) {
  return `You are doing individual B2B sales prospecting research for Spokeo (identity verification, people search, and contact/address history API) targeting HR & Staffing companies as buyers who need to verify the identity of candidates, temp workers, or gig/marketplace providers quickly and accurately during hiring or onboarding.

For EACH of these ${group.length} companies, do the following:
${group.map(companyLine).join('\n')}

For each company:
1. Use the ZoomInfo search_contacts_v2 tool with companyIdList: [companyId], managementLevelList: ["VP Level Exec","Director","C Level Exec"], departmentList including Operations, Human Resources, or similar. Look for a real decision-influencer: VP/Director of Operations, Talent Acquisition/Recruiting, Trust & Safety, Compliance, or similar. Prefer a result where hasEmail is true.
2. Use ZoomInfo enrich_contacts (by personId) to get their verified email, phone, and LinkedIn URL, and confirm job title/company.
3. Use ZoomInfo enrich_company_signals (you can batch up to 10 company IDs in one call) to find one concrete, current hook for a cold email opener: a funding round, product launch, leadership move, hiring surge, or press mention. If nothing useful comes back, fall back to a role-based hook about identity verification at hiring speed/scale for that specific role.
4. Check whether this contact or company already exists in HubSpot using the HubSpot search_crm_objects or query_crm_data tool (search by email and by company name). If they already exist as a contact or associated company in the CRM, do NOT draft outreach — set skip: true, skipReason: "already in HubSpot CRM".
5. If you cannot find any qualifying VP/Director/C-level contact with a usable email in Operations, HR, Recruiting, Trust & Safety, or Compliance, set skip: true, skipReason: "no qualified contact found".
6. Otherwise, draft a 4-touch outbound sequence for this contact, following these strict rules:
   - No em dashes. Never write "I hope this email finds you well," "touching base," "circling back," "synergy," "leverage" as a verb, or "solutions."
   - Short paragraphs, 2-3 sentences max per paragraph. Active voice. Conversational, not templated-sounding. No bullet lists inside the emails.
   - Initial email: opening line is the specific hook (not a generic compliment), next 1-2 sentences state the pain the hook implies, then one sentence on how Spokeo's identity verification / people data API addresses it (no product dump), then ONE low-friction call to action (e.g. "worth a 15-minute conversation?" rather than "can we get on a call?").
   - Follow-up 1 (send ~day 3-5): one sentence, bump the thread, don't re-explain anything.
   - Follow-up 2 (send ~day 8-10): 2-3 sentences, add a new angle, data point, or different framing of the problem.
   - Follow-up 3 (send ~day 15-20): the graceful breakup email; acknowledge they may not be interested, leave the door open, gracious tone.
   - Provide a subject line only for the initial email.

Return exactly one record per company in the group, in the same order the companies were listed, even for the ones you skip.`
}

const batchResults = await parallel(
  groups.map(group => () => agent(batchPromptFor(group), { phase: 'Research & draft', schema: BATCH_SCHEMA }))
)

const allRecords = batchResults.filter(Boolean).flatMap(r => r.records || [])
const usable = allRecords.filter(r => !r.skip && r.email && !excludeEmails.has(String(r.email).toLowerCase()))
const skipped = allRecords.filter(r => r.skip || !r.email)

log(`${usable.length} usable contacts drafted; ${skipped.length} skipped.`)

const finalBatch = usable.slice(0, batchSize)
if (usable.length > finalBatch.length) {
  log(`${usable.length - finalBatch.length} additional qualified contacts were found beyond the ${batchSize}-per-day cap; they were dropped from today's batch, not carried over.`)
}

return {
  batch: finalBatch,
  discoveredCount: (discovery.companies || []).length,
  candidateCount: candidates.length,
  skippedCount: skipped.length,
  skipReasons: skipped.map(s => s.skipReason).filter(Boolean),
  nextPage: page + 1,
}
