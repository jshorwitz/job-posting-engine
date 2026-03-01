# 18-Email Cold Outbound Sequence

## Overview

Full-funnel cold outbound sequence triggered when a company posts a growth/marketing leadership role. Each email covers a different Synter product angle and uses enrichment data to make it concrete and personal.

**Target persona:** CEO/Founder at a company hiring a Head of Growth, VP Marketing, or similar.
**Signal:** Job posting discovered via Sumble.
**Sending platform:** Loops.so (existing integration, automation with delays).
**Enrichment sources:** SpyFu, BuiltWith, Firecrawl, Sumble job data.
**Deliverability:** Use a separate sending domain (e.g., `mail.syntermedia.ai`) to protect primary domain.

---

## Instantly CSV Upload Template

All enrichment data is pre-computed by the engine and exported as a single CSV. Each column becomes a custom variable available in every email step via `{{ColumnName}}` syntax.

### CSV Columns (Instantly Format)

> Column names must start with capital letters, max 20 chars, no duplicates.
> Save as UTF-8. Email column is required and must be first.

```csv
Email,First Name,Last Name,Company Name,Title,Phone,Personalization,Jobtitle,Companydomain,Monthlyspend,Annualspend,Ppckeywords,Organickeywords,Paidclicks,Organicclicks,Domainstrength,Topcompetitor,Competitorspend,Sharedkeywords,Gapkeyword,Gapkeywordcpc,Topheadline,Topaddays,Totalads,Installedpixels,Missingpixels,Pixelcount,Orgclickvalue,Seotop10,Topadnetwork,Wastekeywords,Estimatedsavings,Techstack,Crmtool,Analyticstool,Siteheadline,Callink
```

### Column Definitions

| Column | Source | Description | Fallback |
|--------|--------|-------------|----------|
| `Email` | Hunter/Apollo | Work email (required) | — |
| `First Name` | Sumble/Apollo | First name | "there" |
| `Last Name` | Sumble/Apollo | Last name | "" |
| `Company Name` | Sumble | Company name | "your company" |
| `Title` | Sumble | Contact's job title | "" |
| `Phone` | Apollo | Phone number | "" |
| `Personalization` | AI-generated | Custom opening line for Email 1 | "" |
| `Jobtitle` | Sumble | Role they're hiring for | "growth leader" |
| `Companydomain` | Sumble | Company website | "" |
| `Monthlyspend` | SpyFu `getDomainStats` → `monthlyPpcBudget` | "$15,000" formatted | "" |
| `Annualspend` | SpyFu `getDomainStats` → `adSpendAnnual` | "$180,000" formatted | "" |
| `Ppckeywords` | SpyFu `getDomainStats` → `ppcKeywordCount` | "342" | "" |
| `Organickeywords` | SpyFu `getDomainStats` → `organicKeywordCount` | "1,205" | "" |
| `Paidclicks` | SpyFu `getDomainStats` → `monthlyPaidClicks` | "8,400" | "" |
| `Organicclicks` | SpyFu `getDomainStats` → `monthlyOrganicClicks` | "22,000" | "" |
| `Domainstrength` | SpyFu `getDomainStats` → `domainStrength` | "62/100" | "" |
| `Topcompetitor` | SpyFu `getCompetitors` → top PPC competitor domain | "acme.com" | "your closest competitor" |
| `Competitorspend` | SpyFu `getCompetitors` → competitor's `estimatedBudget` | "$22,000" | "" |
| `Sharedkeywords` | SpyFu `getCompetitors` → `commonKeywords` | "187" | "" |
| `Gapkeyword` | SpyFu `getKombatAnalysis` → top gap opportunity keyword | "best crm software" | "" |
| `Gapkeywordcpc` | SpyFu `getKombatAnalysis` → gap keyword CPC | "$4.20" | "" |
| `Topheadline` | SpyFu `getAdHistory` → longest-running ad headline | "Try Acme Free..." | "" |
| `Topaddays` | SpyFu `getAdHistory` → top ad `daysActive` | "247" | "" |
| `Totalads` | SpyFu `getAdHistory` → `totalAds` | "38" | "" |
| `Installedpixels` | BuiltWith `getAdPixels` → detected platforms | "Google, Meta" | "" |
| `Missingpixels` | BuiltWith → platforms NOT detected | "LinkedIn, Reddit, X" | "" |
| `Pixelcount` | BuiltWith → count of installed ad pixels | "2" | "" |
| `Orgclickvalue` | SpyFu `getSEOMetrics` → `organicClickValue` | "$12,400" | "" |
| `Seotop10` | SpyFu `getSEOMetrics` → positions 1-10 count | "89" | "" |
| `Topadnetwork` | SpyFu `getDomainStats` or competitor data | "Google Ads" | "" |
| `Wastekeywords` | SpyFu `getPPCKeywords` → count with position > 8 and CPC > $3 | "47" | "" |
| `Estimatedsavings` | Calculated: `monthlyPpcBudget * 0.20` | "$3,000" | "" |
| `Techstack` | BuiltWith → top 3 technologies | "Shopify, HubSpot, GA4" | "" |
| `Crmtool` | BuiltWith → detected CRM | "HubSpot" | "" |
| `Analyticstool` | BuiltWith → detected analytics | "Google Analytics 4" | "" |
| `Siteheadline` | Firecrawl → main H1 from homepage | "The #1 CRM for..." | "" |
| `Callink` | Settings → `calendly_url` | Calendar booking link | "" |

---

## The 18 Emails

### Narrative Arc

**The cautionary tale.** This sequence tells the prospect exactly what's going
to happen when they hire a paid media person or agency — the 90-day failure
arc — and positions Synter as the smarter alternative. Each email is 1-2
sentences advancing the story, sent every few days.

The sender establishes credibility upfront: 20+ years in paid media, seen
this pattern hundreds of times.

---

### Phase 1: The Setup (Days 0-7) — "Here's how it's going to go"

---

#### Email 1 — The Signal + Who I Am (Day 0)
**Narrative beat:** Establish credibility, name the pattern
**Data used:** `Jobtitle`, `Company Name`, `First Name`

```
Subject: {{Jobtitle|growth}} hire

{{RANDOM|Hi|Hey}} {{First Name|there}},

{{RANDOM|Noticed|Saw}} {{Company Name|your company}} is hiring a {{Jobtitle|growth leader}}.
I've been doing paid media for 20+ years and I've seen what happens
next about a hundred times. Let me save you the suspense.

You're going to hire an agency or a paid media person.
They're going to take 30 days to set up conversion tracking.
Then another 30 days to build landing pages. Then they'll
hand-pick Google Ads, maybe LinkedIn, and burn through
$50-100K before telling you the algorithm needs more time to learn.

There's a faster way. {{RANDOM|Worth 15 min to hear it?|Open to a quick call?}}

{sender_name}
```

---

#### Email 2 — The 30-Day Setup Tax (Day 3)
**Narrative beat:** Conversion tracking delay = money burning
**Data used:** `Monthlyspend`, `Installedpixels`, `Missingpixels`

```
Subject: day 1 of 90

{{First Name|Hi}},

Step one of the agency playbook: spend 30 days setting up
conversion tracking. Pixels, GTM containers, attribution models.

Meanwhile you're spending {{Monthlyspend|real money}} on ads with
no way to measure what's working. {{Company Name|Your site}} has
{{Installedpixels|some}} tracking but is missing {{Missingpixels|several platforms}}.

Synter sets up cross-platform tracking in 10 minutes. Not 30 days.

{sender_name}
```

**Fallback (no SpyFu data):**
```
Subject: day 1 of 90

{{First Name|Hi}},

Step one of the agency playbook: spend 30 days setting up
conversion tracking. Pixels, GTM containers, attribution models.

Meanwhile your ad budget is running with no way to measure
what's working. Synter sets up cross-platform tracking
in 10 minutes. Not 30 days.

{sender_name}
```

---

#### Email 3 — The Landing Page Delay (Day 5)
**Narrative beat:** Another 30 days wasted on landing pages
**Data used:** `Companydomain`, `Siteheadline`

```
Subject: day 30 of 90

{{First Name|Hi}},

Tracking is finally live. Now your agency needs landing pages.
Custom designs, copywriting rounds, dev tickets, QA.
Another 30 days minimum.

Meanwhile every ad click lands on your homepage, which says
"{{Siteheadline|something generic}}" and has 10 different CTAs.

Synter generates dedicated landing pages from a single prompt.
Live in minutes, not months.

{sender_name}
```

---

#### Email 4 — The $50-100K Burn (Day 7)
**Narrative beat:** The budget burn begins, "algorithm learning" excuse
**Data used:** `Monthlyspend`, `Annualspend`

```
Subject: day 60 of 90

{{First Name|Hi}},

Two months in. Tracking works. Landing pages are up.
Now the real spending starts.

Your agency picks Google Ads, maybe LinkedIn.
They burn through $50-100K. Pipeline doesn't move.

When you ask why, you'll hear: "The algorithm needs more data.
We have to train the platform. Give it another quarter."

That's not how it works. You can get results right away
if you target smart from day one.

{sender_name}
```

---

### Phase 2: The Alternative (Days 10-21) — "Here's what actually works"

---

#### Email 5 — Hyper-Targeting vs Spray and Pray (Day 10)
**Narrative beat:** The real way to get results immediately
**Data used:** `Topcompetitor`, `Sharedkeywords`

```
Subject: the algorithm excuse is nonsense

{{First Name|Hi}},

The reason most paid media fails early isn't algorithm training.
It's lazy targeting. Broad keywords, generic audiences, one platform.

The fix: combine multiple ad platforms with hyper-targeting.
Use enrichment data to build tight audiences. Find signals
where there's already buying intent.

{{Topcompetitor|Your closest competitor}} shares {{Sharedkeywords|hundreds of}}
keywords with you. That's a signal. Their audience is your audience.

Synter does this automatically across 7 platforms.

{sender_name}
```

---

#### Email 6 — The Keyword Waste (Day 13)
**Narrative beat:** Where their current budget is leaking
**Data used:** `Monthlyspend`, `Wastekeywords`, `Ppckeywords`, `Estimatedsavings`

```
Subject: {{Wastekeywords|dozens of}} keywords doing nothing

{{First Name|Hi}},

You're bidding on {{Ppckeywords|hundreds of}} PPC keywords at
{{Monthlyspend|your current spend level}}.

{{Wastekeywords|A chunk of}} those are high-CPC terms where
you rank below position 8. You're paying for clicks that
never convert because you're buried on the page.

An agency would review these quarterly. Synter prunes them
daily. Estimated recovery: {{Estimatedsavings|15-25%}} per month.

{sender_name}
```

---

#### Email 7 — The Competitor Gap (Day 16)
**Narrative beat:** What they're missing that competitors aren't
**Data used:** `Topcompetitor`, `Competitorspend`, `Gapkeyword`, `Gapkeywordcpc`

```
Subject: {{Company Name|your}} vs {{Topcompetitor|your top competitor}}

{{First Name|Hi}},

{{Topcompetitor|Your top PPC competitor}} spends {{Competitorspend|more than you'd expect}} per month.
They rank for "{{Gapkeyword|keywords you don't}}" at {{Gapkeywordcpc|premium CPCs}}.

An agency would find this out in month 3. Maybe.
Synter maps every keyword gap in 2 minutes.

{{RANDOM|Want to see the full breakdown?|Want the report?}}

{sender_name}
```

---

#### Email 8 — The Multi-Platform Problem (Day 19)
**Narrative beat:** One platform is never enough
**Data used:** `Pixelcount`, `Missingpixels`

```
Subject: {{Pixelcount|2}} out of 7

{{First Name|Hi}},

Here's another thing your agency won't tell you: one platform
is never enough. Google Ads is competitive and expensive.
You need LinkedIn for B2B, Reddit for communities, Meta for
retargeting, TikTok for awareness.

You're on {{Pixelcount|a couple}} platforms.
Missing: {{Missingpixels|LinkedIn, Reddit, TikTok}}.

Launching on a new platform takes an agency 2-3 weeks.
Synter does it in 10 minutes.

{sender_name}
```

---

### Phase 3: The Math (Days 22-35) — "Here's what it actually costs"

---

#### Email 9 — The Agency Fee Stack (Day 22)
**Narrative beat:** Add up what the traditional path really costs
**Data used:** `Monthlyspend`, `Annualspend`, `Jobtitle`

```
Subject: the real cost

{{First Name|Hi}},

Let me add it up for you:

A {{Jobtitle|Head of Growth}} costs $150-200K loaded.
An agency charges 15-20% of spend on top.
At {{Monthlyspend|your current budget}} that's another $2-3K per month
just in management fees.

Plus 90 days of ramp before anything works.
Plus $50-100K burned on "learning."

Synter costs a fraction of that and starts producing on day one.

{sender_name}
```

---

#### Email 10 — The Ad Copy Problem (Day 25)
**Narrative beat:** Creative testing at human speed vs AI speed
**Data used:** `Topheadline`, `Topaddays`, `Totalads`

```
Subject: {{Totalads|a handful of}} ads running

{{First Name|Hi}},

Your longest-running Google Ad starts with "{{Topheadline|...}}"
and has been live for {{Topaddays|a while}}. That's a winner.

But you only have {{Totalads|a few}} total ads running.
Best practice is 3-5 variants per ad group.

Your agency will brief a copywriter, wait a week, review,
revise, launch. Synter generates and tests variants
automatically, pauses losers, scales winners.

{sender_name}
```

---

#### Email 11 — The SEO Overlap (Day 28)
**Narrative beat:** Paying for clicks you already get free
**Data used:** `Organicclicks`, `Orgclickvalue`, `Monthlyspend`

```
Subject: paying for free clicks

{{First Name|Hi}},

{{Company Name|Your site}} gets {{Organicclicks|thousands of}} organic
clicks per month worth {{Orgclickvalue|real money}}.

But you're also paying {{Monthlyspend|good money}} for PPC keywords
that overlap with your organic rankings.

No agency will tell you to spend less. Synter identifies
the overlap and shifts budget to where organic can't reach.

{sender_name}
```

---

#### Email 12 — Not Another Dashboard (Day 31)
**Narrative beat:** Synter executes, doesn't just report
**Data used:** `Domainstrength`

```
Subject: not another dashboard

{{First Name|Hi}},

You probably have 3 analytics tools already.
You don't need a 4th.

Synter doesn't show you charts. AI agents actually execute.
They create ads, adjust bids, prune keywords, reallocate budgets,
launch on new channels. You tell the agent what you want.
It does the work.

That's the difference between 20 years of doing this
and building another reporting tool.

{{RANDOM|15 min to see it?|Worth a quick look?}}

{sender_name}
```

---

#### Email 13 — The Full ROI Math (Day 34)
**Narrative beat:** Conservative numbers, let them do the math
**Data used:** `Monthlyspend`, `Estimatedsavings`, `Annualspend`

```
Subject: the math

{{First Name|Hi}},

Conservative numbers at {{Monthlyspend|your spend level}}:

Agency management fee saved: 15-20% of spend.
Waste from AI keyword pruning: {{Estimatedsavings|15-25%}} recovered.
Setup time: 90 days → same day.
Time saved: 20+ hours per week of manual campaign work.

Over a year at {{Annualspend|your annual spend}}, that adds up.

{{RANDOM|Want to validate these together?|Worth a 15-min sanity check?}}
{{Callink}}

{sender_name}
```

---

### Phase 4: The Close (Days 37-52) — Offer, proof, last chance

---

#### Email 14 — Free Credits (Day 37)
**Narrative beat:** Remove all risk
**Data used:** None

```
Subject: 200 free credits

{{First Name|Hi}},

I'm giving you 200 free credits to try Synter. No card required.
That's enough to run a full campaign on any platform.

Skip the 90-day agency ramp. See results this week.

syntermedia.ai/get-started

{sender_name}
```

---

#### Email 15 — The Case Study (Day 40)
**Narrative beat:** Someone else did it, here's what happened
**Data used:** `Techstack`

```
Subject: how a {{Techstack|similar}} company cut CPA 35%

{{First Name|Hi}},

A company using {{Techstack|a similar stack}} cut their cost per
acquisition by 35% in 6 weeks after switching to Synter.

Biggest win: automated keyword pruning. They'd been spending
on 200+ keywords that hadn't converted in 90 days.
Their agency never flagged it.

{{RANDOM|Want the details?|Happy to walk you through it.}}

{sender_name}
```

---

#### Email 16 — Both Is the Answer (Day 44)
**Narrative beat:** Synter + the hire, not either/or
**Data used:** `Jobtitle`

```
Subject: hire the person too

{{First Name|Hi}},

I'm not saying don't hire a {{Jobtitle|Head of Growth}}.
I'm saying don't wait for them to start from scratch.

Start Synter now. When your hire shows up in 3 months,
they inherit running campaigns with real data.
Instead of a blank Google Ads account and a to-do list.

{sender_name}
```

---

#### Email 17 — The Pattern Interrupt (Day 48)
**Narrative beat:** Human connection, check assumptions
**Data used:** None

```
Subject: did I miss the mark?

{{First Name|Hi}},

Maybe paid media isn't the bottleneck right now.
Maybe it's something else entirely.

I'd genuinely like to hear what's keeping you up
at night on the growth side. Hit reply, even one line.

{sender_name}
```

---

#### Email 18 — The Clean Break (Day 52)
**Narrative beat:** Summary of the full arc, final CTA
**Data used:** `Monthlyspend`, `Topcompetitor`, `Missingpixels`, `Estimatedsavings`

```
Subject: last one from me

{{First Name|Hi}},

Last email. Here's the full picture:

You're hiring a growth leader. You'll also hire an agency
or build an in-house team. That takes 90 days and $50-100K
before you see results. Maybe.

You spend {{Monthlyspend|real budget}} per month on ads.
{{Topcompetitor|Your closest competitor}} is outspending you.
You're missing {{Missingpixels|several channels}}.
Estimated savings with Synter: {{Estimatedsavings|15-25%}} per month.

I've been doing this for 20+ years. The pattern doesn't change.
Unless you change the approach.

If this ever becomes relevant: {{Callink}}
No hard feelings either way.

{sender_name}
```

---

## Enrichment Pipeline

### Data Collection Order

The engine collects all enrichment data BEFORE generating the CSV export.
This happens in `run_enrichment()`, a new pipeline step.

```
1. Sumble job data         → Jobtitle, Company Name, Companydomain
2. Hunter/Apollo           → Email, First Name, Last Name, Phone
3. SpyFu getDomainStats    → Monthlyspend, Annualspend, Ppckeywords, etc.
4. SpyFu getCompetitors    → Topcompetitor, Competitorspend, Sharedkeywords
5. SpyFu getKombatAnalysis → Gapkeyword, Gapkeywordcpc
6. SpyFu getAdHistory      → Topheadline, Topaddays, Totalads
7. SpyFu getSEOMetrics     → Organicclicks, Orgclickvalue, Seotop10
8. SpyFu getPPCKeywords    → Wastekeywords (computed)
9. BuiltWith getAdPixels   → Installedpixels, Missingpixels, Pixelcount
10. BuiltWith (extended)   → Techstack, Crmtool, Analyticstool
11. Firecrawl              → Siteheadline
12. OpenAI                 → Personalization (AI-generated opening line)
```

### Rate Limiting

- SpyFu: 100 requests/hour (shared with Synter web app if same API key)
- BuiltWith: Respects API limits
- Firecrawl: Standard rate limits
- Process max 20 leads per run to stay within SpyFu limits (7 calls per lead = 140 calls)

### Computed Fields

| Field | Formula |
|-------|---------|
| `Estimatedsavings` | `monthlyPpcBudget * 0.20`, formatted as `$X,XXX` |
| `Annualspend` | `monthlyPpcBudget * 12`, formatted as `$XXX,XXX` |
| `Wastekeywords` | Count of PPC keywords with `position > 8 AND cpc > 3.0` |
| `Missingpixels` | `ALL_PLATFORMS - installedPlatforms`, joined as string |
| `Pixelcount` | `len(installedPlatforms)` |

### Fallback Strategy

When a data source returns no data for a domain:
1. Leave the column empty in the CSV
2. Instantly uses the `{{Variable|fallback}}` syntax in the email template
3. Emails 2, 3, 6, 7, 8, 10, 13, 18 have dedicated fallback versions
4. Emails 9, 14, 16, 17 don't need external data

---

## Coordinated Multi-Channel Timing (ABM Skill)

Following the ABM outbound skill's coordination pattern:

| Day | Email | LinkedIn | Letter (Scribeless) |
|-----|-------|----------|---------------------|
| 0 | Email 1: The Signal | View profile | Letter sent (arrives ~Day 5) |
| 3 | Email 2: Dollar Figure | Connection request | — |
| 5 | Email 3: Competitor Peek | — | Letter arrives |
| 7 | Email 4: Missing Channel | Follow-up if connected | — |
| 10 | Email 5: Tracking Audit | Engage with their content | — |
| 13 | Email 6: Budget Leak | — | — |
| 16 | Email 7: Ad Copy Teardown | — | — |
| 19 | Email 8: Keyword Gap | Share relevant article | — |
| 22 | Email 9: AI Agents | — | — |
| 25 | Email 10: SEO vs Paid | — | — |
| 28 | Email 11: Landing Pages | — | — |
| 31 | Email 12: Cross-Platform | View profile again | — |
| 34 | Email 13: ROI Calculator | — | — |
| 37 | Email 14: Free Credits | — | 2nd letter with case study |
| 40 | Email 15: Case Study | Like their post | 2nd letter arrives |
| 44 | Email 16: Hiring Cost | — | — |
| 48 | Email 17: Pattern Interrupt | — | — |
| 52 | Email 18: Clean Break | — | — |

---

## Implementation Checklist

- [x] Create `engine/clients/spyfu.py` (port from `apps/web/src/lib/spyfu/client.ts`)
- [x] Create `engine/clients/builtwith.py` (port from `apps/web/src/lib/builtwith.ts`)
- [x] Create `engine/clients/firecrawl.py` (simple homepage scraper)
- [x] Add SpyFu + BuiltWith + Firecrawl settings to `engine/config.py`
- [x] Create `engine/enrichment.py` — orchestrates all data collection per lead
- [x] Create `engine/export/instantly_csv.py` — exports enriched leads to Instantly CSV format
- [x] Update `engine/pipeline.py` — add `run_enrichment()` and `export_csv()` pipeline steps
- [x] Update `.env.example` with new API keys
- [ ] Build 18-step Loop automation in Loops.so UI with delays matching the schedule above
- [ ] Create custom contact properties in Loops for all enrichment fields (Monthlyspend, Topcompetitor, etc.)
- [ ] Configure separate sending domain in Loops (e.g., `mail.syntermedia.ai`) for cold outbound
- [ ] Test with 10 leads end-to-end before scaling

---

## CLI Usage

```bash
# Full pipeline: discover jobs → enrich → export CSV
run-engine --enrich --export instantly

# Enrich only (skip job discovery, use existing leads)
run-engine --enrich-only --export instantly --limit 20

# Dry run (enrich but don't export)
run-engine --enrich --dry-run

# Export to specific file
run-engine --enrich --export instantly --output data/instantly-upload-2026-03-01.csv
```
