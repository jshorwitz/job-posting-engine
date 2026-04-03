# 8-Email Cold Outbound Sequence — AI Agents Time Savings

## Overview

Tighter 8-email cold outbound sequence targeting Heads of Marketing hiring for performance/growth/demand gen roles. Leads with value — the Synter manual as a gift, AI agents as the time-saver, Synter as the shortcut. Every email gives something, not sells.

**Target persona:** Heads of Marketing / VPs of Marketing / Directors of Marketing hiring for Performance Marketing, Growth Marketing, or Demand Generation roles.
**Signal:** Job posting discovered via Sumble.
**Sending platform:** SmartLead.
**Enrichment sources:** SpyFu, BuiltWith, Firecrawl, Sumble job data.
**Lead magnet:** syntermedia.ai/manual — "Growth Marketing in the Age of AI Agents"
**Core angle:** "Master AI agents, save 20+ hours/week. Synter gives you a substantial head start."

---

## SmartLead CSV Upload Template

All enrichment data is pre-computed by the engine and exported as a single CSV. Each column becomes a custom variable available in every email step via `{{ColumnName}}` syntax.

### CSV Columns (SmartLead Format)

> Column names must start with capital letters, max 20 chars, no duplicates.
> Save as UTF-8. Email column is required and must be first.

```csv
Email,First Name,Last Name,Company Name,Title,Phone,Jobtitle,Companydomain,Monthlyspend,Annualspend,Ppckeywords,Organickeywords,Topcompetitor,Competitorspend,Installedpixels,Missingpixels,Pixelcount,Wastekeywords,Estimatedsavings,Callink
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
| `Jobtitle` | Sumble | Role they're hiring for | "performance marketer" |
| `Companydomain` | Sumble | Company website | "" |
| `Monthlyspend` | SpyFu `getDomainStats` → `monthlyPpcBudget` | "$15,000" formatted | "" |
| `Annualspend` | SpyFu `getDomainStats` → `adSpendAnnual` | "$180,000" formatted | "" |
| `Ppckeywords` | SpyFu `getDomainStats` → `ppcKeywordCount` | "342" | "" |
| `Organickeywords` | SpyFu `getDomainStats` → `organicKeywordCount` | "1,205" | "" |
| `Topcompetitor` | SpyFu `getCompetitors` → top PPC competitor domain | "acme.com" | "your closest competitor" |
| `Competitorspend` | SpyFu `getCompetitors` → competitor's `estimatedBudget` | "$22,000" | "" |
| `Installedpixels` | BuiltWith `getAdPixels` → detected platforms | "Google, Meta" | "" |
| `Missingpixels` | BuiltWith → platforms NOT detected | "LinkedIn, Reddit, X" | "" |
| `Pixelcount` | BuiltWith → count of installed ad pixels | "2" | "" |
| `Wastekeywords` | SpyFu `getPPCKeywords` → count with position > 8 and CPC > $3 | "47" | "" |
| `Estimatedsavings` | Calculated: `monthlyPpcBudget * 0.20` | "$3,000" | "" |
| `Callink` | Settings → `calendly_url` | Calendar booking link | "" |

---

## The 8 Emails

### Narrative Arc

**The AI Agent Advantage.** This sequence leads with value — the manual as the
gift, AI agents as the time-saver, Synter as the shortcut. Each email gives
something useful while building the case that AI agents are the competitive
edge their new hire needs. The sender has 20+ years in paid media and
has seen the shift firsthand.

---

### Phase 1: The Gift (Days 0-5) — "Here's something valuable"

---

#### Email 1 — The Guide (Day 0)
**Narrative beat:** Offer the manual as a genuine resource, establish relevance
**Data used:** `Jobtitle`, `Company Name`, `First Name`

```
Subject: {{Jobtitle|performance marketing}} hire

{{RANDOM|Hi|Hey}} {{First Name|there}},

{{RANDOM|Noticed|Saw}} {{Company Name|your company}} is hiring a {{Jobtitle|performance marketer}}. We just published what I think is the most comprehensive guide to growth marketing with AI agents — covers workflows, prompt patterns, and the tools that actually save time.

Thought your new hire might want it on day one: syntermedia.ai/manual

No pitch. Just a resource from someone who's been doing paid media for 20+ years.

{sender_name}
```

---

#### Email 2 — The Time Math (Day 3)
**Narrative beat:** Quantify the time waste, show the AI agent alternative
**Data used:** `First Name`, `Company Name`

```
Subject: 10 hours/week back

{{First Name|Hi}},

Most performance marketers spend their week like this:

Weekly reporting: 4 hours.
Account audits: 2 hours.
Campaign setup and QA: 3 hours.
Competitor research: 2 hours.

That's 10+ hours/week on work AI agents handle in minutes. The manual I sent covers exactly how — chapter 3 breaks down each workflow with the prompts and tools.

Your {{Jobtitle|new hire}} at {{Company Name|your company}} shouldn't spend their first 90 days doing what a machine can do in 90 seconds.

{sender_name}
```

---

### Phase 2: The Proof (Days 7-14) — "Here's the evidence"

---

#### Email 3 — The Competitive Edge (Day 7)
**Narrative beat:** Show what AI agents can surface instantly using their own data
**Data used:** `Topcompetitor`, `Competitorspend`, `Monthlyspend`, `First Name`, `Company Name`

```
Subject: {{Topcompetitor|your competitor}}'s ad budget

{{First Name|Hi}},

Quick example of what an AI agent can do in 30 seconds:

{{Topcompetitor|Your closest competitor}} is spending {{Competitorspend|more than you}} per month on paid media. You're at {{Monthlyspend|your current level}}. That gap matters — and your new hire would need weeks of manual research to find it.

An AI agent surfaces this in one prompt. The manual walks through exactly how to build competitive intelligence workflows that run on autopilot.

syntermedia.ai/manual — section 4, competitive analysis.

{sender_name}
```

**Fallback (no SpyFu data):**
```
Subject: what your competitors are spending

{{First Name|Hi}},

Quick example of what an AI agent can do in 30 seconds:

Your closest competitors' ad budgets, keyword strategies, and top-performing ad copy — all surfaced in one prompt. Your new hire would need weeks of manual research to compile the same analysis.

The manual walks through exactly how to build competitive intelligence workflows that run on autopilot.

syntermedia.ai/manual — section 4, competitive analysis.

{sender_name}
```

---

#### Email 4 — The Platform Problem (Day 10)
**Narrative beat:** Cross-platform complexity, AI agents as the unifier
**Data used:** `Pixelcount`, `Missingpixels`, `Installedpixels`, `First Name`, `Company Name`

```
Subject: {{Pixelcount|2}} platforms isn't enough

{{First Name|Hi}},

{{Company Name|Your company}} is running ads on {{Pixelcount|a couple of}} platforms ({{Installedpixels|Google, Meta}}). You're missing: {{Missingpixels|LinkedIn, Reddit, X, TikTok}}.

One marketer managing 10+ platforms manually is impossible. One marketer with AI agents managing 10+ platforms is Tuesday.

Synter connects to Google, Meta, LinkedIn, Reddit, X, TikTok, Microsoft, Amazon, Pinterest, and Snapchat — all from one interface. Your {{Jobtitle|new hire}} gets a command center, not a tab-switching nightmare.

{sender_name}
```

**Fallback (no BuiltWith data):**
```
Subject: the platform problem

{{First Name|Hi}},

Most companies run ads on 2-3 platforms. They should be on 6-8. The reason they're not? One marketer can't manage that many dashboards.

One marketer with AI agents can. Synter connects to Google, Meta, LinkedIn, Reddit, X, TikTok, Microsoft, Amazon, Pinterest, and Snapchat — all from one interface. Your {{Jobtitle|new hire}} gets a command center, not a tab-switching nightmare.

{sender_name}
```

---

#### Email 5 — The $49 vs $150K Question (Day 14)
**Narrative beat:** ROI math — Synter vs hire cost vs agency cost
**Data used:** `Jobtitle`, `First Name`

```
Subject: $49/mo vs $150K/yr

{{First Name|Hi}},

A {{Jobtitle|performance marketing}} hire costs $120-180K loaded. An agency charges 15-20% of spend. Both take 90 days to ramp.

Synter costs $49/mo flat. No percentage-of-spend fees. No seat limits.

Give your new hire Synter on day one. They inherit a platform that already knows your competitive landscape, manages campaigns across 10+ channels, and optimizes 24/7. They skip the ramp and start with leverage.

{sender_name}
```

---

### Phase 3: The Close (Days 18-28) — "Here's how to start"

---

#### Email 6 — The MCP Difference (Day 18)
**Narrative beat:** Technical differentiator for savvy marketers
**Data used:** `First Name`

```
Subject: ads from inside your AI assistant

{{First Name|Hi}},

Synter is the only ad platform with an MCP server. That means your team can manage campaigns from inside Claude, ChatGPT, Cursor, Amp, or Windsurf.

No dashboard tab-switching. No context loss. Ask your AI assistant to pause underperforming campaigns, reallocate budget, or generate new ad copy — and it actually executes.

This is what the Campaign IDE concept is about. It's in chapter 6 of the manual: syntermedia.ai/manual

{sender_name}
```

---

#### Email 7 — Free Credits (Day 23)
**Narrative beat:** Remove all risk, direct CTA
**Data used:** `First Name`

```
Subject: 1,000 free credits

{{First Name|Hi}},

1,000 free credits. No card required. Enough to run a full campaign across any platform.

Skip the 90-day agency ramp. See results this week.

syntermedia.ai/get-started

{sender_name}
```

---

#### Email 8 — The Clean Break (Day 28)
**Narrative beat:** Summary, last touch, low pressure
**Data used:** `First Name`, `Jobtitle`

```
Subject: last one from me

{{First Name|Hi}},

Last email. Here's the quick summary:

You're hiring a {{Jobtitle|performance marketer}}. AI agents will make them 10x more effective from day one. We wrote the guide on how: syntermedia.ai/manual

Synter is $49/mo flat, works with every major AI assistant, and covers 10+ ad platforms. 1,000 free credits, no card required.

If this ever becomes relevant: {{Callink}}
No hard feelings either way.

{sender_name}
```

---

## Enrichment Pipeline

### Data Collection Order

The engine collects all enrichment data BEFORE generating the CSV export.
This uses the same `run_enrichment()` pipeline step as the 18-email sequence.

```
1. Sumble job data         → Jobtitle, Company Name, Companydomain
2. Hunter/Apollo           → Email, First Name, Last Name, Phone
3. SpyFu getDomainStats    → Monthlyspend, Annualspend, Ppckeywords, Organickeywords
4. SpyFu getCompetitors    → Topcompetitor, Competitorspend
5. BuiltWith getAdPixels   → Installedpixels, Missingpixels, Pixelcount
6. Calculated              → Estimatedsavings
```

### Rate Limiting

- SpyFu: 100 requests/hour (shared with Synter web app if same API key)
- BuiltWith: Respects API limits
- Process max 20 leads per run to stay within SpyFu limits (3 SpyFu calls per lead = 60 calls)

### Computed Fields

| Field | Formula |
|-------|---------|
| `Estimatedsavings` | `monthlyPpcBudget * 0.20`, formatted as `$X,XXX` |
| `Annualspend` | `monthlyPpcBudget * 12`, formatted as `$XXX,XXX` |
| `Missingpixels` | `ALL_PLATFORMS - installedPlatforms`, joined as string |
| `Pixelcount` | `len(installedPlatforms)` |

### Fallback Strategy

When a data source returns no data for a domain:
1. Leave the column empty in the CSV
2. SmartLead uses the `{{Variable|fallback}}` syntax in the email template
3. Emails 3 and 4 have dedicated fallback versions
4. Emails 1, 2, 5, 6, 7, 8 don't require enrichment data

---

## CLI Usage

```bash
# Full pipeline: discover jobs → enrich → export CSV for SmartLead
run-engine --enrich --export smartlead

# Enrich only (skip job discovery, use existing leads)
run-engine --enrich-only --export smartlead --limit 20

# Dry run (enrich but don't export)
run-engine --enrich --dry-run

# Export to specific file
run-engine --enrich --export smartlead --output data/smartlead-ai-agents-2026-04-02.csv
```
