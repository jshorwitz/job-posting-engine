"""Deterministic Vector website-visitor outbound copy.

The Vector campaign should not rely on generic AI copy. Website-visitor outreach
needs softer intent framing, a concrete paid-media pain, and a low-friction CTA.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VectorEmailStep:
    subject: str
    body: str


@dataclass(frozen=True)
class VectorEmailSequence:
    initial: VectorEmailStep
    follow_up: VectorEmailStep
    final: VectorEmailStep


def first_name(full_name: str | None) -> str:
    name = (full_name or "").strip()
    if not name:
        return "there"
    return name.split()[0].strip(",")


def render_vector_visitor_sequence(contact_name: str | None) -> VectorEmailSequence:
    """Return the approved 3-step Vector visitor sequence."""
    first = first_name(contact_name)
    return VectorEmailSequence(
        initial=VectorEmailStep(
            subject="quick question on paid media",
            body=(
                f"{first},\n\n"
                "Saw someone from your team looking at Synter.\n\n"
                "We help teams running ads across Google, Meta, LinkedIn, Reddit, "
                "and other channels replace manual campaign ops with AI agents that "
                "can launch, pause, adjust budgets, and report on performance from "
                "one workflow.\n\n"
                'Usually the pain is not "more dashboards." It is getting changes '
                "made quickly without bouncing between ad platforms.\n\n"
                "Worth sending over a 2-minute overview?\n\n"
                "Joel"
            ),
        ),
        follow_up=VectorEmailStep(
            subject="RE: quick question on paid media",
            body=(
                f"{first},\n\n"
                "The simplest way to think about Synter:\n\n"
                "Your team describes the campaign or optimization they want. The "
                "agent checks tracking, builds the changes, previews them, and "
                "executes across the ad platforms you already use.\n\n"
                "Useful when teams are managing multi-channel spend but do not want "
                "another reporting-only dashboard.\n\n"
                "Should I send the short walkthrough?\n\n"
                "Joel"
            ),
        ),
        final=VectorEmailStep(
            subject="closing the loop",
            body=(
                f"{first},\n\n"
                "Closing the loop here.\n\n"
                "If paid media is already spread across multiple platforms, Synter is "
                "built to remove the manual campaign work: launch changes, budget "
                "moves, creative swaps, and reporting from one agent workflow.\n\n"
                "No need to book time now. Happy to just send the 2-minute walkthrough "
                "if useful.\n\n"
                "Joel"
            ),
        ),
    )


def render_vector_visitor_email(contact_name: str | None) -> tuple[str, str]:
    """Return the initial subject/body used when adding a lead to Smartlead."""
    step = render_vector_visitor_sequence(contact_name).initial
    return step.subject, step.body
