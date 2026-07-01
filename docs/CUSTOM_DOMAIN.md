# Custom domain setup (AgentEdge)

Use a branded URL such as **`https://app.edgebet.com`** instead of the default Vercel URL.

## 1. Vercel — attach the domain

1. Open [Vercel](https://vercel.com) → project **sports-agent** (or your frontend project).
2. **Settings** → **Domains** → **Add**.
3. Enter your domain, e.g. `app.edgebet.com` (subdomain is recommended; keep root `edgebet.com` for marketing if needed).
4. Vercel shows DNS records. At your registrar (GoDaddy, Cloudflare, Namecheap, etc.):

   | Type | Name | Value |
   |------|------|--------|
   | `CNAME` | `app` | `cname.vercel-dns.com` |

   (Use the exact values Vercel displays.)

5. Wait for DNS to propagate (often 5–30 minutes). Vercel will issue HTTPS automatically.

6. Optional: keep `sports-agent-phi.vercel.app` as an alias during migration, or set a redirect in Vercel from the old URL to the new one.

## 2. Vercel — environment variables

**Settings** → **Environment Variables** → add or update for **Production**:

| Variable | Example value |
|----------|----------------|
| `NEXT_PUBLIC_APP_URL` | `https://app.edgebet.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://nlfalrpuspdezfnlakrv.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | *(your anon key)* |
| `NEXT_PUBLIC_API_URL` | `https://sportsagent-production.up.railway.app` |

Redeploy after saving (Deployments → ⋮ → Redeploy).

## 3. Supabase — auth URLs

Dashboard → **Authentication** → **URL Configuration**:

| Field | Value |
|-------|--------|
| **Site URL** | `https://app.edgebet.com` |
| **Redirect URLs** (add each) | `https://app.edgebet.com/auth/callback` |
| | `https://app.edgebet.com/reset-password` |
| | `https://app.edgebet.com/**` |

Keep the old Vercel URLs in the list until you fully migrate:

- `https://sports-agent-phi.vercel.app/auth/callback`
- `https://sports-agent-phi.vercel.app/reset-password`

## 4. Railway — backend CORS

Set **FRONTEND_URL** to your new domain (comma-separate to allow both during migration):

```bash
FRONTEND_URL=https://app.edgebet.com,https://sports-agent-phi.vercel.app
```

Redeploy the Railway service after updating variables.

## 5. Verify

1. Open `https://app.edgebet.com/login` — page loads with HTTPS.
2. Sign in (or reset password after rate limit clears).
3. **POSITIONS** (`/dashboard`) loads WC + MLB cards (no CORS error in browser console).
4. Request a password reset — email link should point to `app.edgebet.com`, not `vercel.app`.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Login works on Vercel URL but not custom domain | Add custom domain to `FRONTEND_URL` on Railway |
| Reset link goes to old URL | Set `NEXT_PUBLIC_APP_URL` on Vercel and redeploy |
| “Invalid redirect URL” on reset | Add new URLs in Supabase Redirect URLs |
| API / CORS errors | Railway `FRONTEND_URL` must include exact origin (no trailing slash) |
