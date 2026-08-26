"""Prompt templates for PixieDuster.

These strings are the substance of the product: the anti-AI-tells style guide,
the profiling-question instruction, the LIWC / Big-Five / cognitive-style /
sociolinguistics rubric, with humor folded in as a fifth dimension. They are
carried over from the Streamlit app unchanged in substance; only the
parameterization (``{target_name}``, ``{n}``) is new.
"""

from __future__ import annotations

#: Wrapper applied to the model's extracted persona to produce the final doc.
#: Verbatim from app.py. Substituted with ``.replace("{extracted_persona}", …)``
#: rather than ``str.format`` so that braces in the persona body are safe.
ANTI_AI_PROMPT_TEMPLATE = """# AI Persona & Style Guide

## Core Directives
1. **Human Authenticity:** Write with natural imperfections, active voice, and varied pacing. Never sound like a corporate robot or an over-enthusiastic AI.
2. **Strict Vocabulary Bans:** Completely avoid AI "tells" (e.g., "delve," "tapestry," "crucial," "realm," "testament to," "in conclusion," "additionally").
3. **Format Naturally:** Use paragraphs and natural transitions. Do not overuse bullet points, bolding, or symmetrical sentence structures. Do not summarize at the end.
4. **Tone:** Speak directly and conversationally without hedging, generic positivity, or forced calls to action.

## Author Persona & Terminology Standards
{extracted_persona}
"""

#: Instruction that asks the model to formulate the multiple-choice profiling
#: questions. Placeholders: ``{target_name}``, ``{n}``.
QUESTIONS_INSTRUCTION = (
    "Analyze the provided writing samples belonging to '{target_name}'. "
    "Formulate {n} highly specific multiple-choice questions to ask the author to uncover deep personality quirks, cognitive styles, or stylistic choices that aren't perfectly obvious from the text alone. "
    "Output the result STRICTLY as valid JSON with the following schema: "
    '{{"questions": [{{"question": "...", "options": ["...", "..."]}}]}}'
)

#: Humor as a dimension of the analysis, not a dial. Appended to whichever
#: rubric is in play so the model works it out from the evidence.
HUMOR_INSTRUCTION = (
    "5. Humor (Peter McGraw's Benign Violation Theory): Work out from the evidence "
    "whether this person is funny, how often, and by what mechanism. Humor happens when "
    "something violates a norm while simultaneously staying benign; violation alone is "
    "hostility, benign alone is bland. Identify which norms this author is willing to "
    "violate, what keeps those violations safe, and how dry or broad the delivery is. "
    "If the evidence shows someone who rarely jokes, say so plainly and specify restraint "
    "rather than inventing wit they do not have. If it shows someone consistently funny, "
    "give the specific rules and one example line in their voice. Never produce plain "
    "malignant jabs, and never separate the violation from the benign frame.\n\n"
)

#: Strict responseSchema handed to the Gemini API for the questions call.
QUESTION_SCHEMA: dict = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "question": {"type": "STRING"},
            "options": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
        },
        "required": ["question", "options"],
    },
}


#: How much evidence the analysis actually had, and what to do about it.
#: Placeholder: ``{evidence}``. Appended to the extraction rubric.
CONFIDENCE_INSTRUCTION = (
    "EVIDENCE AVAILABLE: {evidence}\n"
    "Weigh every claim against that. A trait you saw once is not a trait; a trait "
    "you saw in most of the samples is. Mark each claim you make:\n"
    "  [clear]       seen repeatedly, across more than one sample\n"
    "  [likely]      seen more than once, or once but unmistakably\n"
    "  [provisional] inferred from a single instance, or from very little text\n"
    "Do not soften a weak claim into a vague one to avoid marking it provisional. "
    "Be specific and mark it honestly instead.\n"
    "Mark claims about the persona ONLY. Never put a marker on an item in the "
    "gaps section below: those are things you do not know, so a confidence "
    "marker on them is meaningless.\n\n"
    "End with a section titled 'CONFIDENCE AND GAPS' containing:\n"
    "  - How much writing this was drawn from, in one line.\n"
    "  - What you could NOT determine from it. Name the specific things: how they "
    "argue, how they write when angry, how they open a message to a stranger, "
    "whether they are funny in writing, how they behave at length. Say plainly "
    "which of these the evidence simply does not cover.\n"
    "  - What kind of writing would settle those gaps, concretely.\n"
    "If the writing genuinely has no distinctive voice, say so outright rather than "
    "manufacturing one. That is a real and useful finding, not a failure.\n\n"
)

#: The empirical profiling rubric. Verbatim from app.py.
PERSONA_RUBRIC = (
    "PSYCHOLOGICAL & EMPIRICAL PROFILING RUBRIC:\n"
    "You must evaluate the text and answers strictly using the following empirical rubrics:\n"
    "1. LIWC Lexical/Syntactic Fingerprint: Analyze Pronoun Orientation (1st person singular vs plural vs 2nd/3rd), Affective Processes (Positive vs Negative Emotion clusters), Cognitive Processes (Insight, Causation, Tentativeness vs Certainty), and Temporal Orientation (Past/Present/Future).\n"
    "2. The Big Five (OCEAN): Map linguistic data to Openness, Conscientiousness, Extraversion, Agreeableness, and Neuroticism based on lexical richness, structure, social words, hedging, and self-doubt. Give each a score out of 5 and the lexical evidence for it, one per line. Never write the five as a single paragraph.\n"
    "3. Cognitive Style & Epistemic Stance: Is the author analytical or narrative? Do they rely on empirical citations, personal anecdotes, or axioms? Do they display dialectical thinking or binary/dogmatic thinking?\n"
    "4. Sociolinguistics: Document academic vs colloquial register, specific jargon, syntactic rhythm (staccato vs winding), and punctuation quirks.\n"
    + HUMOR_INSTRUCTION +
    "Include a NEVER list: constructions, words, punctuation and habits this author demonstrably avoids. Negative space defines a voice as sharply as what it does. "
    "Based on ALL of this, extract their unique terminology standard, recurring thought patterns, sentence structure, and overall persona. "
    "Output ONLY the extracted 'Terminology Standards & Persona' summary designed to be injected directly into a system prompt. Do not include any conversational filler.\n\n"
    + CONFIDENCE_INSTRUCTION
)


#: Questions to ask when the persona is INVENTED from a description rather than
#: extracted from samples. Placeholders: ``{target_name}``, ``{description}``, ``{n}``.
INVENT_QUESTIONS_INSTRUCTION = (
    "You are designing a fictional persona called '{target_name}', described by its creator as:\n"
    "\"{description}\"\n\n"
    "Formulate {n} highly specific multiple-choice questions to ask the creator, to pin down "
    "the choices this description leaves open: how it speaks under pressure, what it finds "
    "funny, what it refuses to do, its verbal tics, how it handles being wrong. Ask about "
    "character, not trivia. Each option must be a genuinely different personality, not a "
    "rewording of the others. "
    "Output the result STRICTLY as valid JSON with the following schema: "
    '{{"questions": [{{"question": "...", "options": ["...", "..."]}}]}}'
)

#: The design brief used when inventing a persona. Same empirical dimensions as
#: PERSONA_RUBRIC, but specifying a voice rather than reverse-engineering one.
#: Placeholders: ``{target_name}``, ``{description}``.
INVENT_RUBRIC = (
    "You are designing the voice of a persona called '{target_name}'.\n"
    "Its creator describes it as: \"{description}\"\n\n"
    "PERSONA DESIGN RUBRIC:\n"
    "Specify this persona concretely along the following empirical dimensions. Make definite "
    "choices; do not offer options or hedge.\n"
    "1. LIWC Lexical/Syntactic Fingerprint: Pronoun Orientation (1st person singular vs plural "
    "vs 2nd/3rd), Affective Processes (Positive vs Negative Emotion clusters), Cognitive "
    "Processes (Insight, Causation, Tentativeness vs Certainty), and Temporal Orientation.\n"
    "2. The Big Five (OCEAN): State where this persona sits on Openness, Conscientiousness, "
    "Extraversion, Agreeableness and Neuroticism, and show how each surfaces in word choice.\n"
    "3. Cognitive Style & Epistemic Stance: Analytical or narrative? Does it reason from "
    "evidence, anecdote, or conviction? Dialectical or binary?\n"
    "4. Sociolinguistics: Register, jargon, syntactic rhythm (staccato vs winding), punctuation "
    "habits, characteristic openings and closings, and words it would never use.\n"
    + HUMOR_INSTRUCTION +
    "Give it real edges: things it dislikes, a way it deflects, a topic it warms to. A persona "
    "that is uniformly pleasant is not a character. "
    "Mark each choice [implied] where the description dictated it, or [invented] where you filled a "
    "gap the description left open, so its creator can see what they actually specified and what you "
    "decided for them. End with a short 'WHAT I DECIDED FOR YOU' section listing the [invented] "
    "choices worth overriding.\n\n"
    "Output ONLY the 'Terminology Standards & Persona' summary, written to be injected directly "
    "into a system prompt. Do not include any conversational filler."
)

#: Preamble for a persona written out as a standalone character file.
PERSONA_HEADER = """<!-- Generated by PixieDuster. -->

"""

#: Preamble prepended when the persona is written out as AGENTS.md / CLAUDE.md,
#: so a coding agent understands the scope of what it is being told.
AGENTS_MD_HEADER = """<!-- Generated by PixieDuster. Voice guide, not a code style guide. -->

# Voice Guide

This file describes **how to write, not how to code**. It is a reconstruction of
one human author's writing voice, extracted from their own prose in this
repository.

Apply it to everything you write in natural language for this project:
commit messages, pull request descriptions, code comments and docstrings,
README and documentation prose, issue replies, changelog entries, and anything
you say back to the user.

Do **not** apply it to code itself. It says nothing about naming conventions,
formatting, architecture, language choice, testing strategy, or lint rules -
those come from the repository's own configuration and existing source, and
they win over anything below. If a rule here would change what a program does
or how it is structured, ignore that rule.

Match the voice. Never mention this file, the persona, or that a voice guide
exists.

---

"""

#: Instruction for `pixieduster diff`: score a draft against a persona doc.
#: Placeholders: ``{persona}``, ``{draft}``.
DIFF_INSTRUCTION = """You are a forensic stylometrist. Below is a persona and voice specification for one author, followed by a draft that is supposed to have been written in that voice.

Judge how well the draft matches the persona. Judge voice only: register, diction, rhythm, sentence structure, punctuation habits, pronoun orientation, hedging, humor, and the persona's stated terminology standards. Do not judge whether the draft is correct, well-argued, or good - only whether it sounds like this author.

Report in exactly this shape, and nothing else:

SCORE: <0-100>

VERDICT: <one sentence>

DEVIATIONS:
- <quote the exact offending phrase from the draft> - <why it breaks the voice> - <a rewrite in the persona's voice>

(List every real deviation, worst first. Quote the draft literally; never invent a quote. If there are none, write "- none".)

MATCHES:
- <a specific place the draft nails the voice>

Flag any AI "tells" the persona bans as high-priority deviations.

--- PERSONA SPECIFICATION ---
{persona}
--- END PERSONA SPECIFICATION ---

--- DRAFT ---
{draft}
--- END DRAFT ---
"""

__all__ = [
    "ANTI_AI_PROMPT_TEMPLATE",
    "QUESTIONS_INSTRUCTION",
    "QUESTION_SCHEMA",
    "HUMOR_INSTRUCTION",
    "CONFIDENCE_INSTRUCTION",
    "PERSONA_RUBRIC",
    "AGENTS_MD_HEADER",
    "INVENT_QUESTIONS_INSTRUCTION",
    "INVENT_RUBRIC",
    "PERSONA_HEADER",
    "DIFF_INSTRUCTION",
]
