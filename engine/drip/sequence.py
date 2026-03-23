"""18-email drip sequence — The Cautionary Tale.

Each email is stored as a dict with:
  - step: 1-18
  - delay_days: days to wait AFTER the previous email
  - subject: subject line with {{var|fallback}} placeholders
  - body: email body with {{var|fallback}} placeholders

Placeholders are resolved in Python via render_template() before
being pushed to Loops as contact properties.

Available Synter/SimilarWeb placeholders (from enrichment.py):
  - {{synter_monthly_visits}}     — Monthly website traffic
  - {{synter_bounce_rate}}        — Bounce rate %
  - {{synter_paid_search_pct}}    — Paid search traffic %
  - {{synter_organic_pct}}        — Organic search traffic %
  - {{synter_mobile_pct}}         — Mobile traffic %
  - {{synter_global_rank}}        — Global website rank
  - {{mediaplan_tier}}            — enterprise/growth/starter/launch
  - {{mediaplan_total_budget}}    — Recommended total budget
  - {{mediaplan_channels}}        — Recommended channels
  - {{mediaplan_uplift_pct}}      — Projected traffic uplift %
  - {{mediaplan_talking_points}}  — Auto-generated insights
"""

from __future__ import annotations

import re
from typing import Any


def render_template(template: str, data: dict[str, Any]) -> str:
    """Replace {{var}} and {{var|fallback}} with values from data.

    - {{var}} → data["var"] or empty string
    - {{var|fallback text}} → data["var"] or "fallback text"
    """

    def _replace(match: re.Match) -> str:
        expr = match.group(1)
        if "|" in expr:
            key, fallback = expr.split("|", 1)
        else:
            key, fallback = expr, ""
        key = key.strip()
        fallback = fallback.strip()
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val)
        return fallback

    return re.sub(r"\{\{(.+?)\}\}", _replace, template)


# ── Phase 1: The Setup (Days 0-7) ───────────────────────────────

_EMAIL_1 = {
    "step": 1,
    "delay_days": 0,
    "subject": "{{jobTitleHiring|growth}} hire",
    "body": """\
Hi {{firstName|there}},

Saw {{company|your company}} is hiring a {{jobTitleHiring|growth leader}}.
I pulled your traffic data — {{synter_monthly_visits|your site}} gets
{{synter_monthly_visits|decent traffic}} monthly visits but only
{{synter_paid_search_pct|minimal}}% comes from paid channels.

I've been doing paid media for 20+ years and I've seen what happens
next about a hundred times. You hire an agency. They spend 30 days
on tracking, 30 days on landing pages, then burn through $50-100K
before telling you the algorithm needs more time.

There's a faster way. Worth 15 min to hear it?

Joel""",
}

_EMAIL_2 = {
    "step": 2,
    "delay_days": 3,
    "subject": "day 1 of 90",
    "body": """\
{{firstName|Hi}},

Step one of the agency playbook: spend 30 days setting up
conversion tracking. Pixels, GTM containers, attribution models.

Meanwhile you're spending {{spyfu_monthly_spend|real money}} on ads with
no way to measure what's working. {{company|Your site}} has
{{builtwith_installed_pixels|some}} tracking but is missing {{builtwith_missing_pixels|several platforms}}.

Synter sets up cross-platform tracking in 10 minutes. Not 30 days.

Joel""",
}

_EMAIL_3 = {
    "step": 3,
    "delay_days": 2,
    "subject": "day 30 of 90",
    "body": """\
{{firstName|Hi}},

Tracking is finally live. Now your agency needs landing pages.
Custom designs, copywriting rounds, dev tickets, QA.
Another 30 days minimum.

Meanwhile every ad click lands on your homepage, which says
"{{firecrawl_headline|something generic}}" and has 10 different CTAs.

Synter generates dedicated landing pages from a single prompt.
Live in minutes, not months.

Joel""",
}

_EMAIL_4 = {
    "step": 4,
    "delay_days": 2,
    "subject": "day 60 of 90",
    "body": """\
{{firstName|Hi}},

Two months in. Tracking works. Landing pages are up.
Now the real spending starts.

Your agency picks Google Ads, maybe LinkedIn.
They burn through $50-100K. Pipeline doesn't move.

When you ask why, you'll hear: "The algorithm needs more data.
We have to train the platform. Give it another quarter."

That's not how it works. You can get results right away
if you target smart from day one.

Joel""",
}

# ── Phase 2: The Alternative (Days 10-21) ───────────────────────

_EMAIL_5 = {
    "step": 5,
    "delay_days": 3,
    "subject": "the algorithm excuse is nonsense",
    "body": """\
{{firstName|Hi}},

The reason most paid media fails early isn't algorithm training.
It's lazy targeting. Broad keywords, generic audiences, one platform.

Your site gets {{synter_monthly_visits|solid}} visits/month —
{{synter_organic_pct|most}}% organic, {{synter_paid_search_pct|almost nothing}}% paid.
That organic traffic tells you exactly what your audience searches for.
Now imagine running paid on those same terms across 7 platforms.

{{spyfu_top_competitor|Your closest competitor}} shares {{spyfu_shared_keywords|hundreds of}}
keywords with you. Their audience is your audience.

Synter does this automatically.

Joel""",
}

_EMAIL_6 = {
    "step": 6,
    "delay_days": 3,
    "subject": "{{spyfu_waste_keywords|dozens of}} keywords doing nothing",
    "body": """\
{{firstName|Hi}},

You're bidding on {{spyfu_ppc_keywords|hundreds of}} PPC keywords at
{{spyfu_monthly_spend|your current spend level}}.

{{spyfu_waste_keywords|A chunk of}} of those are high-CPC terms where
you rank below position 8. You're paying for clicks that
never convert because you're buried on the page.

An agency would review these quarterly. Synter prunes them
in real time, every day.

Joel""",
}

_EMAIL_7 = {
    "step": 7,
    "delay_days": 3,
    "subject": "your best ad is {{spyfu_top_ad_days|old}} days old",
    "body": """\
{{firstName|Hi}},

Your top-performing ad copy — "{{spyfu_top_headline|...}}" —
has been running for {{spyfu_top_ad_days|a while}} days.

That's either really good creative or really stale optimization.
Out of {{spyfu_total_ads|a handful of}} total ads, how many have been
tested against it?

Synter generates and tests ad variants automatically.
Not quarterly. Continuously.

Joel""",
}

_EMAIL_8 = {
    "step": 8,
    "delay_days": 3,
    "subject": "{{spyfu_gap_keyword|keyword gap}}",
    "body": """\
{{firstName|Hi}},

"{{spyfu_gap_keyword|keywords you're missing}}" — CPC is {{spyfu_gap_keyword_cpc|premium}}.

{{spyfu_top_competitor|Your top competitor}} is bidding on it. You're not.
That's one keyword. There are hundreds more where your
competitors show up and you don't.

An agency finds these gaps in a quarterly review.
Synter runs gap analysis every day across 7 platforms.

Joel""",
}

# ── Phase 3: The Math (Days 22-35) ──────────────────────────────

_EMAIL_9 = {
    "step": 9,
    "delay_days": 3,
    "subject": "what if the agency was an AI agent",
    "body": """\
{{firstName|Hi}},

I built a media plan for {{company|your company}} based on your
traffic profile ({{synter_monthly_visits|your current}} visits/mo,
{{synter_bounce_rate|moderate}}% bounce rate, {{synter_mobile_pct|majority}}% mobile).

Here's what it looks like:
- Channels: {{mediaplan_channels|Google, Meta, LinkedIn, Retargeting}}
- Projected uplift: {{mediaplan_uplift_pct|50-100%}} more traffic in 90 days
- Budget: ${{mediaplan_total_budget|8,000}} over the first 8 weeks

That's not a pitch deck. That's what Synter's AI agents
would actually execute — setup in minutes, not months.

Worth 15 min to walk through it?

Joel""",
}

_EMAIL_10 = {
    "step": 10,
    "delay_days": 3,
    "subject": "your organic clicks are worth {{spyfu_organic_click_value|real money}}",
    "body": """\
{{firstName|Hi}},

You have {{spyfu_seo_top10|many}} keywords in the top 10 organic results.
Those organic clicks are worth {{spyfu_organic_click_value|thousands}} per month
if you had to buy them as ads.

Most agencies ignore organic entirely. They only look at paid.
Synter factors both into your strategy because the real question
isn't "how much should I spend on ads?" — it's "where should
I spend vs where do I already rank?"

Joel""",
}

_EMAIL_11 = {
    "step": 11,
    "delay_days": 3,
    "subject": "10 minutes to a landing page",
    "body": """\
{{firstName|Hi}},

Every ad platform needs a dedicated landing page.
That's 7 platforms x multiple campaigns x A/B variants.

Agencies charge $2-5K per page. Takes 2-4 weeks each.
Synter generates them from a single prompt. Live in minutes.

Each one gets automatic tracking pixels for every platform
you're running on. No developer needed.

Joel""",
}

_EMAIL_12 = {
    "step": 12,
    "delay_days": 3,
    "subject": "7 platforms, 1 agent",
    "body": """\
{{firstName|Hi}},

{{company|Your company}} has {{builtwith_installed_pixels|some}} tracking installed.
That means you're running on those platforms.

But you're missing {{builtwith_missing_pixels|several others}}.
Each missing platform is an audience you're not reaching.

An agency typically runs 1-2 platforms well. Synter runs all 7:
Google, Meta, LinkedIn, Reddit, X, TikTok, Microsoft.
Same budget, broader reach, AI-optimized across all of them.

Joel""",
}

_EMAIL_13 = {
    "step": 13,
    "delay_days": 3,
    "subject": "the math",
    "body": """\
{{firstName|Hi}},

Let me make this concrete for {{company|your company}}:

Current: {{synter_monthly_visits|your}} visits/mo, {{synter_paid_search_pct|minimal}}% paid.
Projected: {{mediaplan_projected_visits_low|much more}}-{{mediaplan_projected_visits_high|significantly more}} visits/mo in 90 days.
Budget: ${{mediaplan_total_budget|reasonable}} over 8 weeks.
Channels: {{mediaplan_channels|Google, Meta, LinkedIn, Retargeting}}.

Plus at {{spyfu_monthly_spend|your current ad spend}}:
- Agency fee saved: 15-20% of spend
- Waste from keyword pruning: 15-25% recovered
- Setup: 90 days → same day

Worth a 15-min sanity check?
{{settings_calendly_url}}

Joel""",
}

# ── Phase 4: The Close (Days 37-52) ─────────────────────────────

_EMAIL_14 = {
    "step": 14,
    "delay_days": 3,
    "subject": "200 free credits",
    "body": """\
{{firstName|Hi}},

I'm giving you 200 free credits to try Synter. No card required.
That's enough to run a full campaign on any platform.

Skip the 90-day agency ramp. See results this week.

syntermedia.ai/get-started

Joel""",
}

_EMAIL_15 = {
    "step": 15,
    "delay_days": 3,
    "subject": "how a {{builtwith_tech_stack|similar}} company cut CPA 35%",
    "body": """\
{{firstName|Hi}},

A company using {{builtwith_tech_stack|a similar stack}} cut their cost per
acquisition by 35% in 6 weeks after switching to Synter.

Biggest win: automated keyword pruning. They'd been spending
on 200+ keywords that hadn't converted in 90 days.
Their agency never flagged it.

Happy to walk you through it.

Joel""",
}

_EMAIL_16 = {
    "step": 16,
    "delay_days": 4,
    "subject": "hire the person too",
    "body": """\
{{firstName|Hi}},

I'm not saying don't hire a {{jobTitleHiring|Head of Growth}}.
I'm saying don't wait for them to start from scratch.

Start Synter now. When your hire shows up in 3 months,
they inherit running campaigns with real data.
Instead of a blank Google Ads account and a to-do list.

Joel""",
}

_EMAIL_17 = {
    "step": 17,
    "delay_days": 4,
    "subject": "did I miss the mark?",
    "body": """\
{{firstName|Hi}},

Maybe paid media isn't the bottleneck right now.
Maybe it's something else entirely.

I'd genuinely like to hear what's keeping you up
at night on the growth side. Hit reply, even one line.

Joel""",
}

_EMAIL_18 = {
    "step": 18,
    "delay_days": 4,
    "subject": "last one from me",
    "body": """\
{{firstName|Hi}},

Last email. Here's the full picture:

{{company|Your company}} gets {{synter_monthly_visits|decent}} visits/mo.
Only {{synter_paid_search_pct|a fraction}}% from paid channels.
{{spyfu_top_competitor|Your closest competitor}} is outspending you.
You're missing {{builtwith_missing_pixels|several channels}}.

I built a custom media plan: {{mediaplan_channels|Google, Meta, LinkedIn}}
for ${{mediaplan_total_budget|a reasonable budget}} that could drive
{{mediaplan_uplift_pct|50-100%}} more traffic in 90 days.

I've been doing this for 20+ years. The pattern doesn't change.
Unless you change the approach.

If this ever becomes relevant: {{settings_calendly_url}}
No hard feelings either way.

Joel""",
}


DRIP_SEQUENCE: list[dict[str, Any]] = [
    _EMAIL_1,
    _EMAIL_2,
    _EMAIL_3,
    _EMAIL_4,
    _EMAIL_5,
    _EMAIL_6,
    _EMAIL_7,
    _EMAIL_8,
    _EMAIL_9,
    _EMAIL_10,
    _EMAIL_11,
    _EMAIL_12,
    _EMAIL_13,
    _EMAIL_14,
    _EMAIL_15,
    _EMAIL_16,
    _EMAIL_17,
    _EMAIL_18,
]
