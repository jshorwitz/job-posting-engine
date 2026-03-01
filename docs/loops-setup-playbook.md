# Loops.so Setup Playbook — 18-Email Cold Outbound

> **Executable by Claude Cowork.** Each section has either API calls (run via curl)
> or step-by-step UI instructions. Complete in order.

---

## Prerequisites

- `LOOPS_API_KEY` set in Doppler (synter-media project, prd config)
- Access to Loops dashboard: https://app.loops.so
- DNS access for `syntermedia.ai` (for sending domain)

```bash
# Verify API key works
curl -s "https://app.loops.so/api/v1/contacts/properties?list=all" \
  -H "Authorization: Bearer $LOOPS_API_KEY" | head -20
```

---

## Step 1: Create Contact Properties via API

Loops auto-creates custom properties when you upsert a contact with new fields.
Run this single API call to bootstrap all 25 enrichment properties at once
using a dummy test contact (delete it after).

```bash
curl -X PUT "https://app.loops.so/api/v1/contacts/update" \
  -H "Authorization: Bearer $LOOPS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test-property-bootstrap@synter-internal.com",
    "firstName": "Test",
    "lastName": "Bootstrap",
    "source": "property-bootstrap",
    "subscribed": false,
    "company": "Test Corp",
    "spyfu_monthly_spend": "$15,000",
    "spyfu_annual_spend": "$180,000",
    "spyfu_ppc_keywords": "342",
    "spyfu_organic_keywords": "1,205",
    "spyfu_paid_clicks": "8,400",
    "spyfu_organic_clicks": "22,000",
    "spyfu_domain_strength": "62",
    "spyfu_top_competitor": "competitor.com",
    "spyfu_competitor_spend": "$22,000",
    "spyfu_shared_keywords": "187",
    "spyfu_gap_keyword": "best crm software",
    "spyfu_gap_keyword_cpc": "$4.20",
    "spyfu_top_headline": "Try Acme Free Today",
    "spyfu_top_ad_days": "247",
    "spyfu_total_ads": "38",
    "spyfu_organic_click_value": "$12,400",
    "spyfu_seo_top10": "89",
    "spyfu_top_ad_network": "Google Ads",
    "spyfu_waste_keywords": "47",
    "builtwith_installed_pixels": "Google, Meta",
    "builtwith_missing_pixels": "LinkedIn, Reddit, X",
    "builtwith_pixel_count": "2",
    "builtwith_tech_stack": "React, Next.js, Vercel",
    "builtwith_crm_tool": "HubSpot",
    "builtwith_analytics_tool": "Google Analytics 4",
    "firecrawl_headline": "The #1 Platform for Growth Teams",
    "ai_personalization": "Congrats on the growth hire — bold move given Q1.",
    "settings_calendly_url": "https://calendly.com/synter/15min",
    "jobTitleHiring": "Head of Growth"
  }'
```

### Verify properties were created

```bash
curl -s "https://app.loops.so/api/v1/contacts/properties?list=all" \
  -H "Authorization: Bearer $LOOPS_API_KEY" | python3 -m json.tool
```

You should see all 25+ custom properties listed.

### Delete the bootstrap contact

```bash
curl -X POST "https://app.loops.so/api/v1/contacts/delete" \
  -H "Authorization: Bearer $LOOPS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email": "test-property-bootstrap@synter-internal.com"}'
```

---

## Step 2: Create Mailing List

> **UI: Loops → Audience → Lists → Create List**

- **Name:** `Cold Outreach - Job Posting Engine`
- **Description:** Leads from job posting signals, enriched with SpyFu/BuiltWith data
- Copy the **List ID** from the list settings page

### Update Doppler with the list ID

```bash
doppler secrets set LOOPS_MAILING_LIST_ID=<paste_list_id_here> \
  --project synter-media --config prd
```

---

## Step 3: Configure Sending Domain

> **UI: Loops → Settings → Sending**

### 3a. Add sending domain

1. Go to **Settings → Sending → Add Domain**
2. Enter: `mail.syntermedia.ai`
3. Loops will show DNS records to add

### 3b. Add DNS records

Add these to your DNS provider (Cloudflare/Vercel) for `mail.syntermedia.ai`:

| Type | Name | Value | Purpose |
|------|------|-------|---------|
| CNAME | `mail.syntermedia.ai` | (provided by Loops) | Sending domain |
| TXT | `mail.syntermedia.ai` | (provided by Loops) | SPF |
| CNAME | `loopskey1._domainkey.mail.syntermedia.ai` | (provided by Loops) | DKIM |
| CNAME | `loopskey2._domainkey.mail.syntermedia.ai` | (provided by Loops) | DKIM |
| TXT | `_dmarc.mail.syntermedia.ai` | `v=DMARC1; p=none; rua=mailto:joel@syntermedia.ai` | DMARC |

### 3c. Verify domain

1. Wait 5-10 minutes for DNS propagation
2. Click **Verify** in Loops
3. All records should show green checkmarks

### 3d. Set as default for cold outreach

Set the **From address** for the automation to: `joel@mail.syntermedia.ai`

---

## Step 4: Build the 18-Email Loop Automation

> **UI: Loops → Loops → Create Loop**

### Trigger

- **Trigger type:** Contact added to list
- **List:** `Cold Outreach - Job Posting Engine`

### Automation Steps

Build the following sequence. Each email step uses `{{property_name}}` merge tags
that map to the contact properties created in Step 1.

**Sender:** `joel@mail.syntermedia.ai`
**Reply-to:** `joel@syntermedia.ai` (so replies go to real inbox)

---

#### Email 1 — Day 0: The Signal

- **Delay:** None (immediate on list add)
- **Subject:** `{{jobTitleHiring}} hire`
- **Body:**

```
Hi {{firstName}},

Saw {{company}} is hiring a {{jobTitleHiring}}.
I've been doing paid media for 20+ years and I've seen what happens
next about a hundred times. Let me save you the suspense.

You're going to hire an agency or a paid media person.
They're going to take 30 days to set up conversion tracking.
Then another 30 days to build landing pages. Then they'll
hand-pick Google Ads, maybe LinkedIn, and burn through
$50-100K before telling you the algorithm needs more time to learn.

There's a faster way. Worth 15 min to hear it?

Joel
```

---

#### Email 2 — Day 3: The 30-Day Setup Tax

- **Delay:** 3 days
- **Subject:** `day 1 of 90`
- **Body:**

```
{{firstName}},

Step one of the agency playbook: spend 30 days setting up
conversion tracking. Pixels, GTM containers, attribution models.

Meanwhile you're spending {{spyfu_monthly_spend}} on ads with
no way to measure what's working. {{company}} has
{{builtwith_installed_pixels}} tracking but is missing {{builtwith_missing_pixels}}.

Synter sets up cross-platform tracking in 10 minutes. Not 30 days.

Joel
```

---

#### Email 3 — Day 5: The Landing Page Delay

- **Delay:** 2 days
- **Subject:** `day 30 of 90`
- **Body:**

```
{{firstName}},

Tracking is finally live. Now your agency needs landing pages.
Custom designs, copywriting rounds, dev tickets, QA.
Another 30 days minimum.

Meanwhile every ad click lands on your homepage, which says
"{{firecrawl_headline}}" and has 10 different CTAs.

Synter generates dedicated landing pages from a single prompt.
Live in minutes, not months.

Joel
```

---

#### Email 4 — Day 7: The $50-100K Burn

- **Delay:** 2 days
- **Subject:** `day 60 of 90`
- **Body:**

```
{{firstName}},

Two months in. Tracking works. Landing pages are up.
Now the real spending starts.

Your agency picks Google Ads, maybe LinkedIn.
They burn through $50-100K. Pipeline doesn't move.

When you ask why, you'll hear: "The algorithm needs more data.
We have to train the platform. Give it another quarter."

That's not how it works. You can get results right away
if you target smart from day one.

Joel
```

---

#### Email 5 — Day 10: Hyper-Targeting

- **Delay:** 3 days
- **Subject:** `the algorithm excuse is nonsense`
- **Body:**

```
{{firstName}},

The reason most paid media fails early isn't algorithm training.
It's lazy targeting. Broad keywords, generic audiences, one platform.

The fix: combine multiple ad platforms with hyper-targeting.
Use enrichment data to build tight audiences. Find signals
where there's already buying intent.

{{spyfu_top_competitor}} shares {{spyfu_shared_keywords}}
keywords with you. That's a signal. Their audience is your audience.

Synter does this automatically across 7 platforms.

Joel
```

---

#### Email 6 — Day 13: The Keyword Waste

- **Delay:** 3 days
- **Subject:** `{{spyfu_waste_keywords}} keywords doing nothing`
- **Body:**

```
{{firstName}},

You're bidding on {{spyfu_ppc_keywords}} PPC keywords at
{{spyfu_monthly_spend}}.

{{spyfu_waste_keywords}} of those are high-CPC terms where
you rank below position 8. You're paying for clicks that
never convert because you're buried on the page.

An agency would review these quarterly. Synter prunes them
in real time, every day.

Joel
```

---

#### Email 7 — Day 16: Ad Copy Teardown

- **Delay:** 3 days
- **Subject:** `your best ad is {{spyfu_top_ad_days}} days old`
- **Body:**

```
{{firstName}},

Your top-performing ad copy — "{{spyfu_top_headline}}" —
has been running for {{spyfu_top_ad_days}} days.

That's either really good creative or really stale optimization.
Out of {{spyfu_total_ads}} total ads, how many have been
tested against it?

Synter generates and tests ad variants automatically.
Not quarterly. Continuously.

Joel
```

---

#### Email 8 — Day 19: The Keyword Gap

- **Delay:** 3 days
- **Subject:** `{{spyfu_gap_keyword}}`
- **Body:**

```
{{firstName}},

"{{spyfu_gap_keyword}}" — CPC is {{spyfu_gap_keyword_cpc}}.

{{spyfu_top_competitor}} is bidding on it. You're not.
That's one keyword. There are hundreds more where your
competitors show up and you don't.

An agency finds these gaps in a quarterly review.
Synter runs gap analysis every day across 7 platforms.

Joel
```

---

#### Email 9 — Day 22: AI Agents

- **Delay:** 3 days
- **Subject:** `what if the agency was an AI agent`
- **Body:**

```
{{firstName}},

Imagine the agency model but:
- Setup in minutes, not months
- Monitors all 7 ad platforms, not just Google
- Optimizes daily, not quarterly
- Costs credits, not 15-20% of spend

That's what Synter is. AI agents that execute your campaigns.
Not a dashboard. Not analytics. Actual execution.

Joel
```

---

#### Email 10 — Day 25: SEO vs Paid

- **Delay:** 3 days
- **Subject:** `your organic clicks are worth {{spyfu_organic_click_value}}`
- **Body:**

```
{{firstName}},

You have {{spyfu_seo_top10}} keywords in the top 10 organic results.
Those organic clicks are worth {{spyfu_organic_click_value}} per month
if you had to buy them as ads.

Most agencies ignore organic entirely. They only look at paid.
Synter factors both into your strategy because the real question
isn't "how much should I spend on ads?" — it's "where should
I spend vs where do I already rank?"

Joel
```

---

#### Email 11 — Day 28: Landing Pages

- **Delay:** 3 days
- **Subject:** `10 minutes to a landing page`
- **Body:**

```
{{firstName}},

Every ad platform needs a dedicated landing page.
That's 7 platforms × multiple campaigns × A/B variants.

Agencies charge $2-5K per page. Takes 2-4 weeks each.
Synter generates them from a single prompt. Live in minutes.

Each one gets automatic tracking pixels for every platform
you're running on. No developer needed.

Joel
```

---

#### Email 12 — Day 31: Cross-Platform

- **Delay:** 3 days
- **Subject:** `7 platforms, 1 agent`
- **Body:**

```
{{firstName}},

{{company}} has {{builtwith_installed_pixels}} tracking installed.
That means you're running on those platforms.

But you're missing {{builtwith_missing_pixels}}.
Each missing platform is an audience you're not reaching.

An agency typically runs 1-2 platforms well. Synter runs all 7:
Google, Meta, LinkedIn, Reddit, X, TikTok, Microsoft.
Same budget, broader reach, AI-optimized across all of them.

Joel
```

---

#### Email 13 — Day 34: ROI Calculator

- **Delay:** 3 days
- **Subject:** `the math`
- **Body:**

```
{{firstName}},

Conservative numbers at {{spyfu_monthly_spend}}:

Agency management fee saved: 15-20% of spend.
Waste from AI keyword pruning: 15-25% recovered.
Setup time: 90 days → same day.
Time saved: 20+ hours per week of manual campaign work.

Over a year at {{spyfu_annual_spend}}, that adds up.

Worth a 15-min sanity check?
{{settings_calendly_url}}

Joel
```

---

#### Email 14 — Day 37: Free Credits

- **Delay:** 3 days
- **Subject:** `200 free credits`
- **Body:**

```
{{firstName}},

I'm giving you 200 free credits to try Synter. No card required.
That's enough to run a full campaign on any platform.

Skip the 90-day agency ramp. See results this week.

syntermedia.ai/get-started

Joel
```

---

#### Email 15 — Day 40: Case Study

- **Delay:** 3 days
- **Subject:** `how a {{builtwith_tech_stack}} company cut CPA 35%`
- **Body:**

```
{{firstName}},

A company using {{builtwith_tech_stack}} cut their cost per
acquisition by 35% in 6 weeks after switching to Synter.

Biggest win: automated keyword pruning. They'd been spending
on 200+ keywords that hadn't converted in 90 days.
Their agency never flagged it.

Happy to walk you through it.

Joel
```

---

#### Email 16 — Day 44: Both Is the Answer

- **Delay:** 4 days
- **Subject:** `hire the person too`
- **Body:**

```
{{firstName}},

I'm not saying don't hire a {{jobTitleHiring}}.
I'm saying don't wait for them to start from scratch.

Start Synter now. When your hire shows up in 3 months,
they inherit running campaigns with real data.
Instead of a blank Google Ads account and a to-do list.

Joel
```

---

#### Email 17 — Day 48: Pattern Interrupt

- **Delay:** 4 days
- **Subject:** `did I miss the mark?`
- **Body:**

```
{{firstName}},

Maybe paid media isn't the bottleneck right now.
Maybe it's something else entirely.

I'd genuinely like to hear what's keeping you up
at night on the growth side. Hit reply, even one line.

Joel
```

---

#### Email 18 — Day 52: Clean Break

- **Delay:** 4 days
- **Subject:** `last one from me`
- **Body:**

```
{{firstName}},

Last email. Here's the full picture:

You're hiring a growth leader. You'll also hire an agency
or build an in-house team. That takes 90 days and $50-100K
before you see results. Maybe.

You spend {{spyfu_monthly_spend}} per month on ads.
{{spyfu_top_competitor}} is outspending you.
You're missing {{builtwith_missing_pixels}}.

I've been doing this for 20+ years. The pattern doesn't change.
Unless you change the approach.

If this ever becomes relevant: {{settings_calendly_url}}
No hard feelings either way.

Joel
```

---

## Step 5: Activate & Test

### 5a. Send a test lead through the pipeline

```bash
# From the job-posting-engine directory, with Doppler secrets:
doppler run -- python3 -m engine.pipeline --enrich --export loops --dry-run --limit 1
```

### 5b. Verify contact appears in Loops

```bash
curl -s "https://app.loops.so/api/v1/contacts/find?email=<test_lead_email>" \
  -H "Authorization: Bearer $LOOPS_API_KEY" | python3 -m json.tool
```

Check that all enrichment properties are populated.

### 5c. Test the automation

1. In Loops, find the test contact
2. Manually add them to the `Cold Outreach - Job Posting Engine` list
3. Verify Email 1 sends immediately
4. Check the automation shows the contact in the flow

### 5d. Go live

Once confirmed:

```bash
# Remove --dry-run for real execution
doppler run -- python3 -m engine.pipeline --enrich --export loops --limit 5
```

Monitor in Loops → Loops → your automation → Activity tab.

---

## Automation Delay Summary

| Step | Email | Delay | Cumulative Day |
|------|-------|-------|----------------|
| 1 | The Signal | Immediate | 0 |
| 2 | 30-Day Setup Tax | +3 days | 3 |
| 3 | Landing Page Delay | +2 days | 5 |
| 4 | $50-100K Burn | +2 days | 7 |
| 5 | Hyper-Targeting | +3 days | 10 |
| 6 | Keyword Waste | +3 days | 13 |
| 7 | Ad Copy Teardown | +3 days | 16 |
| 8 | Keyword Gap | +3 days | 19 |
| 9 | AI Agents | +3 days | 22 |
| 10 | SEO vs Paid | +3 days | 25 |
| 11 | Landing Pages | +3 days | 28 |
| 12 | Cross-Platform | +3 days | 31 |
| 13 | ROI Calculator | +3 days | 34 |
| 14 | Free Credits | +3 days | 37 |
| 15 | Case Study | +3 days | 40 |
| 16 | Both Is the Answer | +4 days | 44 |
| 17 | Pattern Interrupt | +4 days | 48 |
| 18 | Clean Break | +4 days | 52 |

---

## Contact Property Reference

These are the merge tags available in every email:

| Merge Tag | Source | Example Value |
|-----------|--------|---------------|
| `{{firstName}}` | Built-in | Jane |
| `{{lastName}}` | Built-in | Doe |
| `{{company}}` | Built-in | Acme Corp |
| `{{jobTitleHiring}}` | Engine | Head of Growth |
| `{{spyfu_monthly_spend}}` | SpyFu | $15,000 |
| `{{spyfu_annual_spend}}` | SpyFu | $180,000 |
| `{{spyfu_ppc_keywords}}` | SpyFu | 342 |
| `{{spyfu_organic_keywords}}` | SpyFu | 1,205 |
| `{{spyfu_paid_clicks}}` | SpyFu | 8,400 |
| `{{spyfu_organic_clicks}}` | SpyFu | 22,000 |
| `{{spyfu_domain_strength}}` | SpyFu | 62 |
| `{{spyfu_top_competitor}}` | SpyFu | competitor.com |
| `{{spyfu_competitor_spend}}` | SpyFu | $22,000 |
| `{{spyfu_shared_keywords}}` | SpyFu | 187 |
| `{{spyfu_gap_keyword}}` | SpyFu | best crm software |
| `{{spyfu_gap_keyword_cpc}}` | SpyFu | $4.20 |
| `{{spyfu_top_headline}}` | SpyFu | Try Acme Free Today |
| `{{spyfu_top_ad_days}}` | SpyFu | 247 |
| `{{spyfu_total_ads}}` | SpyFu | 38 |
| `{{spyfu_organic_click_value}}` | SpyFu | $12,400 |
| `{{spyfu_seo_top10}}` | SpyFu | 89 |
| `{{spyfu_top_ad_network}}` | SpyFu | Google Ads |
| `{{spyfu_waste_keywords}}` | SpyFu | 47 |
| `{{builtwith_installed_pixels}}` | BuiltWith | Google, Meta |
| `{{builtwith_missing_pixels}}` | BuiltWith | LinkedIn, Reddit, X |
| `{{builtwith_pixel_count}}` | BuiltWith | 2 |
| `{{builtwith_tech_stack}}` | BuiltWith | React, Next.js, Vercel |
| `{{builtwith_crm_tool}}` | BuiltWith | HubSpot |
| `{{builtwith_analytics_tool}}` | BuiltWith | Google Analytics 4 |
| `{{firecrawl_headline}}` | Firecrawl | The #1 Platform for Growth |
| `{{ai_personalization}}` | OpenAI | Congrats on the growth hire |
| `{{settings_calendly_url}}` | Config | https://calendly.com/synter/15min |
