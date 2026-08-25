"""Offline tests for pixieduster.relevance.

The fixture corpus below is meant to look like a real person's folder: an
essay, a chatty note, an email with a quoted reply, an invoice, a bank
statement, a JSON export, a duplicate export of the essay, and a stub.
"""

from __future__ import annotations

import pytest

from pixieduster import relevance
from pixieduster.relevance import Scored, score_binary, score_text, strip_quoted, triage
from pixieduster.types import Sample

# --------------------------------------------------------------------------- #
# The corpus
# --------------------------------------------------------------------------- #

ESSAY = """\
I have been thinking about the year we moved, and how little of it I can
actually remember. My mother says I cried for a week. I do not think that's
true, but she is the one who was awake for it, so who am I to argue?

What I do remember is the smell of the hallway. Wet coats, mostly. I used to
sit on the stairs and wait for my father to come home, and I would count the
cars going past to pass the time. Was that every night, or just once? I honestly
could not tell you now.

We were not unhappy. That's the part people get wrong when I tell it. We were
just very tired, all of us, in a way that I did not have a word for until much
later. I think about it whenever someone asks me where I grew up, and I give
them the short answer instead.
"""

NOTE = """\
ok so I finally tried the bread thing and it did not work. I think my oven runs
hot? Or maybe I am just impatient. Either way it came out like a brick and we
ate it anyway with a lot of butter.

Next time I'm going to leave it overnight like she said. I never listen the
first time, that's my whole problem, honestly. Remind me if you see me.
"""

EMAIL_WITH_QUOTE = """\
Thanks for this. I read it twice on the train and I think you're right about the
second half, it does drag. My instinct is to cut the whole middle section and
see what's left. I'd rather it be short and a bit mean than long and polite.
Let me know when you want it back and I will get it to you.

On Tuesday, 3 June 2025 at 09:12, Jo Baker <jo@example.com> wrote:
> Hi, please find attached the latest draft for your review. As discussed in
> our previous correspondence, the deadline for feedback is the end of the
> month. I have incorporated the comments from the last round and made the
> structural changes we agreed. Please let me know if you require any further
> information or clarification regarding the attached document.
>
> Kind regards,
> Jo
"""

INVOICE = """\
INVOICE
Invoice #: 2025-0413
Invoice Date: 04/13/2025
Billing Period: March 2025

BILL TO
Gretchen Boria
14 Elm Street

DESCRIPTION                     QTY     RATE      AMOUNT
Consulting services              12   150.00     1800.00
Materials                         1    240.50      240.50

Subtotal                                         2040.50
Sales tax                                         163.24
TOTAL DUE                                        2203.74

Payment due within 30 days. Remit to the account number listed above.
Terms and conditions apply.
"""

BANK_STATEMENT = """\
MONTHLY ACCOUNT STATEMENT
Statement Period: 01 March 2025 to 31 March 2025
Account Number: ****4417
Routing Number: ****0021

Beginning balance                                 1402.19
03/02  CARD PURCHASE  GROCERY MART                 -84.22
03/04  DIRECT DEPOSIT PAYROLL                     2100.00
03/07  CARD PURCHASE  COFFEE HOUSE                  -6.40
03/11  ACH DEBIT  UTILITY BILL                    -142.88
03/19  CARD PURCHASE  BOOKSHOP                     -31.00
Ending balance                                    3237.69
"""

JSON_EXPORT = """\
[{"id": 1, "title": "grocery", "done": false, "created": "2025-03-01"},
 {"id": 2, "title": "call dentist", "done": true, "created": "2025-03-02"},
 {"id": 3, "title": "renew pass", "done": false, "created": "2025-03-04"},
 {"id": 4, "title": "water plants", "done": true, "created": "2025-03-05"}]
"""

# Same essay, re-exported: a stray header line and different line wrapping.
ESSAY_DUPLICATE = "Exported from Notes on 2025-04-01\n\n" + " ".join(ESSAY.split())

STUB = "back later.\nfeed the cat"

# The dangerous false positive: real personal writing about money.
ESSAY_ABOUT_MONEY = """\
I spent most of March chasing an invoice, which is not how I imagined my thirties
going. Every Monday I would open my account, see that nothing had landed, and
write another email that got slightly less friendly than the one before it.

The worst part is that I liked the work. I still do. But I could not stop doing
the arithmetic in my head at two in the morning, working out how many weeks of
rent I had left if it never came. My partner kept saying it would be fine, and
it was fine, eventually. That's not the same as it being okay.

I have a rule now: I ask for half up front, and I say it out loud on the first
call so that I cannot talk myself out of it later. It feels rude every single
time. I do it anyway.
"""


RESUME = """\
GRETCHEN BORIA
Senior Researcher

EXPERIENCE
2019-2025  Lead Researcher, Somewhere Institute
  Directed a team of six. Published eleven peer reviewed papers.
  Built the lab's data pipeline from scratch.
2015-2019  Postdoctoral Fellow, Elsewhere University

EDUCATION
PhD, Cognitive Science
"""


def sample(origin: str, text: str) -> Sample:
    return Sample(kind="file", origin=origin, text=text)


@pytest.fixture
def corpus() -> list[Sample]:
    return [
        sample("essay.txt", ESSAY),
        sample("note.md", NOTE),
        sample("reply.eml", EMAIL_WITH_QUOTE),
        sample("invoice_march.txt", INVOICE),
        sample("statement.txt", BANK_STATEMENT),
        sample("todos.json", JSON_EXPORT),
        sample("essay-export.txt", ESSAY_DUPLICATE),
        sample("stub.txt", STUB),
    ]


def verdicts(items: list[Scored]) -> dict[str, str]:
    return {item.origin: item.verdict for item in items}


def reasons(kept: list[Scored], rejected: list[Scored]) -> dict[str, str]:
    return {item.origin: item.reason for item in kept + rejected}


# --------------------------------------------------------------------------- #
# The headline behavior
# --------------------------------------------------------------------------- #

def test_personal_writing_is_kept_and_paperwork_is_dropped(corpus):
    kept, rejected = triage(corpus, [])
    keep_names = {item.origin for item in kept}
    drop_names = {item.origin for item in rejected}

    assert {"essay.txt", "note.md", "reply.eml"} <= keep_names
    assert {"invoice_march.txt", "statement.txt", "todos.json", "stub.txt"} <= drop_names


def test_the_reasons_are_specific(corpus):
    kept, rejected = triage(corpus, [])
    why = reasons(kept, rejected)
    assert why["invoice_march.txt"] == "looks like an invoice or statement, not your writing"
    assert why["statement.txt"] == "looks like an invoice or statement, not your writing"
    assert why["todos.json"] == "looks like a data export, not writing"
    assert why["stub.txt"] == "too short to show a voice"
    assert why["essay-export.txt"] == "nearly identical to essay.txt"


def test_reasons_are_short_plain_and_lowercase_first(corpus):
    kept, rejected = triage(corpus, [])
    for item in kept + rejected:
        assert item.reason, item.origin
        assert item.reason[0].islower(), item.reason
        assert len(item.reason) <= 70, item.reason
        assert "--" not in item.reason


def test_nothing_is_silently_discarded(corpus):
    kept, rejected = triage(corpus, [])
    assert len(kept) + len(rejected) == len(corpus)
    assert {i.origin for i in kept} | {i.origin for i in rejected} == {
        s.origin for s in corpus
    }


def test_results_are_sorted_best_first(corpus):
    kept, rejected = triage(corpus, [])
    assert [i.score for i in kept] == sorted((i.score for i in kept), reverse=True)
    assert [i.score for i in rejected] == sorted((i.score for i in rejected), reverse=True)


def test_scores_stay_in_range(corpus):
    kept, rejected = triage(corpus, [])
    assert all(0.0 <= item.score <= 1.0 for item in kept + rejected)


def test_measured_precision_on_the_corpus(corpus):
    """Every personal file kept, every paperwork file dropped: 8 of 8."""
    expected = {
        "essay.txt": "keep",
        "note.md": "keep",
        "reply.eml": "keep",
        "essay-export.txt": "drop",
        "invoice_march.txt": "drop",
        "statement.txt": "drop",
        "todos.json": "drop",
        "stub.txt": "drop",
    }
    kept, rejected = triage(corpus, [])
    actual = {i.origin: "keep" for i in kept}
    actual.update({i.origin: "drop" for i in rejected})
    assert actual == expected


# --------------------------------------------------------------------------- #
# False positives: the expensive direction
# --------------------------------------------------------------------------- #

def test_a_personal_essay_about_money_is_never_dropped():
    kept, rejected = triage([sample("hard-year.md", ESSAY_ABOUT_MONEY)], [])
    assert [i.origin for i in kept] == ["hard-year.md"]
    assert not rejected


def test_personal_essay_about_money_survives_alongside_real_paperwork():
    corpus = [
        sample("hard-year.md", ESSAY_ABOUT_MONEY),
        sample("invoice_march.txt", INVOICE),
    ]
    kept, rejected = triage(corpus, [])
    assert [i.origin for i in kept] == ["hard-year.md"]
    assert [i.origin for i in rejected] == ["invoice_march.txt"]


def test_sustained_first_person_prose_is_protected_from_dropping():
    """Even loaded with boilerplate vocabulary, real prose survives as unsure."""
    loaded = ESSAY_ABOUT_MONEY + (
        "\n\nTerms and conditions. Account number. Total due. Sales tax. "
        "Policy number. Statement period.\n"
    )
    score, _, verdict = score_text(loaded)
    assert verdict != "drop"


def test_a_recipe_style_note_with_numbers_is_not_read_as_a_statement():
    text = (
        "I made this again on Sunday and I think I have finally got it right.\n"
        "I use 500g of flour, 10g of salt, 7g of yeast, 350g of water.\n"
        "I let it sit for 4 hours, which is longer than the book says.\n"
        "My oven only goes to 240 so I leave it a bit longer than that too.\n"
        "It is not fancy but we eat the whole thing every time, so who cares.\n"
    )
    _, _, verdict = score_text(text)
    assert verdict != "drop"


# --------------------------------------------------------------------------- #
# Quoted and forwarded text
# --------------------------------------------------------------------------- #

def test_quoted_reply_is_stripped_not_dropped(corpus):
    kept, _ = triage(corpus, [])
    email = next(i for i in kept if i.origin == "reply.eml")
    assert "Kind regards" not in email.sample.text
    assert "please find attached" not in email.sample.text
    assert "I read it twice on the train" in email.sample.text


def test_a_message_that_is_only_a_quote_is_dropped():
    only_quote = (
        "On Tuesday, 3 June 2025 at 09:12, Jo Baker <jo@example.com> wrote:\n"
        + "> I am writing to confirm the details we discussed.\n" * 6
    )
    kept, rejected = triage([sample("fwd.eml", only_quote)], [])
    assert not kept
    assert rejected[0].reason == "mostly a quoted reply from someone else"


def test_strip_quoted_handles_the_outlook_separator():
    text = "Here is my bit, briefly.\n\n----- Original Message -----\nFrom: Someone\nblah"
    remaining, removed = strip_quoted(text)
    assert remaining == "Here is my bit, briefly."
    assert removed > 0.5


def test_strip_quoted_cuts_a_pasted_header_block():
    text = "my thoughts below\n\nFrom: Jo\nSent: Monday\nTo: me\n\nthe original mail"
    remaining, _ = strip_quoted(text)
    assert "the original mail" not in remaining
    assert "From: Jo" not in remaining
    assert "my thoughts below" in remaining


def test_strip_quoted_cuts_an_unsubscribe_footer():
    text = "hey, are we still on for Thursday?\n\nUnsubscribe from these emails\n"
    remaining, _ = strip_quoted(text)
    assert "Unsubscribe" not in remaining


def test_strip_quoted_leaves_clean_text_alone():
    remaining, removed = strip_quoted(NOTE)
    assert removed < 0.05
    assert remaining.startswith("ok so I finally tried")


def test_strip_quoted_on_empty_text():
    assert strip_quoted("") == ("", 0.0)


# --------------------------------------------------------------------------- #
# Machine-generated text
# --------------------------------------------------------------------------- #

def test_a_log_file_is_dropped():
    text = "\n".join(
        f"2025-03-0{i} 09:1{i}:00 INFO  handler finished in {i}ms" for i in range(1, 9)
    )
    score, reason, verdict = score_text(text)
    assert verdict == "drop"
    assert reason == "looks like a log file, not writing"


def test_a_calendar_export_is_dropped():
    text = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nSUMMARY:Dentist\n"
        "DTSTART:20250304T090000Z\nEND:VEVENT\nEND:VCALENDAR\n" * 3
    )
    _, reason, verdict = score_text(text)
    assert verdict == "drop"
    assert reason == "looks like a data export, not writing"


def test_a_csv_export_is_dropped():
    text = "name,date,amount,category\n" + "\n".join(
        f"row{i},2025-03-0{i},{i}.00,misc" for i in range(1, 9)
    )
    _, _, verdict = score_text(text)
    assert verdict == "drop"


def test_an_auto_reply_is_dropped():
    text = (
        "This is an automated message. Please do not reply to this address.\n"
        "The recipient is out of the office until the 14th and will respond on\n"
        "their return. For anything urgent, contact the support desk. You are\n"
        "receiving this email because a message was sent to this mailbox.\n"
        "Terms and conditions apply to all correspondence with this office.\n"
    )
    _, reason, verdict = score_text(text)
    assert verdict == "drop"
    assert reason == "reads like an automated message"


# --------------------------------------------------------------------------- #
# Near duplicates
# --------------------------------------------------------------------------- #

def test_the_better_copy_of_a_duplicate_pair_survives(corpus):
    kept, rejected = triage(corpus, [])
    assert "essay.txt" in {i.origin for i in kept}
    dupe = next(i for i in rejected if i.origin == "essay-export.txt")
    assert dupe.reason == "nearly identical to essay.txt"


def test_two_different_notes_are_both_kept():
    kept, _ = triage([sample("a.md", ESSAY), sample("b.md", ESSAY_ABOUT_MONEY)], [])
    assert {i.origin for i in kept} == {"a.md", "b.md"}


def test_an_exact_duplicate_is_caught():
    kept, rejected = triage([sample("one.txt", ESSAY), sample("two.txt", ESSAY)], [])
    assert len(kept) == 1
    assert rejected[0].reason.startswith("nearly identical to")


# --------------------------------------------------------------------------- #
# Length
# --------------------------------------------------------------------------- #

def test_a_two_line_stub_is_dropped():
    _, reason, verdict = score_text("back later.\nfeed the cat")
    assert verdict == "drop"
    assert reason == "too short to show a voice"


def test_empty_text_is_dropped():
    score, _, verdict = score_text("   \n  ")
    assert verdict == "drop" and score == 0.0


def test_a_book_length_file_is_penalized_but_not_dropped():
    long_text = ESSAY * 400  # comfortably past MAX_VOICE_CHARS
    assert len(long_text) > relevance.MAX_VOICE_CHARS
    score, reason, verdict = score_text(long_text)
    assert verdict != "drop"
    assert reason == "very long, more like a book than a note"


# --------------------------------------------------------------------------- #
# Binary files
# --------------------------------------------------------------------------- #

def test_a_photo_roll_name_is_kept():
    score, reason, verdict = score_binary("IMG_4821.png", "image/png")
    assert verdict == "keep"
    assert "photo" in reason or "handwriting" in reason


def test_a_financial_pdf_name_is_dropped():
    for name in ("invoice_march.pdf", "W2_2025.pdf", "bank-statement-q1.pdf",
                 "lease_agreement.pdf", "2024_taxes.pdf"):
        _, reason, verdict = score_binary(name, "application/pdf")
        assert verdict == "drop", name
        assert reason == "the file name looks like a financial or legal document"


def test_an_unknown_pdf_is_unsure_not_dropped():
    _, reason, verdict = score_binary("scan001.pdf", "application/pdf")
    assert verdict == "unsure"
    assert reason == "a pdf we cannot check without sending it"


def test_an_unknown_image_is_kept():
    _, _, verdict = score_binary("2025-03-04.jpeg", "image/jpeg")
    assert verdict == "keep"


def test_a_journal_scan_beats_the_pdf_default():
    _, _, verdict = score_binary("journal-1997.pdf", "application/pdf")
    assert verdict == "keep"


def test_binaries_are_triaged_alongside_text(corpus):
    files = [
        ("IMG_4821.png", "image/png", b"\x89PNG"),
        ("invoice_march.pdf", "application/pdf", b"%PDF"),
    ]
    kept, rejected = triage(corpus, files)
    assert "IMG_4821.png" in {i.origin for i in kept}
    assert "invoice_march.pdf" in {i.origin for i in rejected}
    kept_image = next(i for i in kept if i.origin == "IMG_4821.png")
    assert kept_image.sample is None and kept_image.file is not None


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #

def test_the_budget_fills_from_the_best_score_down(corpus):
    kept, rejected = triage(corpus, [], budget_chars=len(NOTE) + 10)
    assert len(kept) == 1
    assert kept[0].score == max(i.score for i in kept + rejected)
    assert "no room left in this run" in {i.reason for i in rejected}


def test_the_budget_never_returns_an_empty_kept_list(corpus):
    kept, _ = triage(corpus, [], budget_chars=1)
    assert len(kept) == 1


def test_the_budget_still_accounts_for_everything(corpus):
    kept, rejected = triage(corpus, [], budget_chars=500)
    assert len(kept) + len(rejected) == len(corpus)


def test_binaries_do_not_consume_the_character_budget(corpus):
    files = [("IMG_4821.png", "image/png", b"\x00" * 4096)]
    kept, _ = triage([], files, budget_chars=10)
    assert [i.origin for i in kept] == ["IMG_4821.png"]


# --------------------------------------------------------------------------- #
# Shape of the contract
# --------------------------------------------------------------------------- #

def test_triage_on_nothing_returns_two_empty_lists():
    assert triage([], []) == ([], [])


def test_triage_does_not_mutate_the_input_samples(corpus):
    before = [s.text for s in corpus]
    triage(corpus, [])
    assert [s.text for s in corpus] == before


def test_verdicts_are_only_the_three_words(corpus):
    kept, rejected = triage(corpus, [])
    assert {i.verdict for i in kept + rejected} <= {"keep", "unsure", "drop"}


def test_a_scored_text_item_carries_a_sample_and_no_file(corpus):
    kept, _ = triage(corpus, [])
    text_item = next(i for i in kept if i.origin == "essay.txt")
    assert isinstance(text_item.sample, Sample)
    assert text_item.file is None
    assert text_item.sample.kind == "file"


def test_a_short_but_personal_note_is_never_dropped():
    """A haiku is too small to measure and still unmistakably somebody's voice."""
    score, reason, verdict = score_text(
        "the kettle again\nsteam on the window\nI am not ready for this day\n"
    )
    assert verdict != "drop"
    assert reason == "short, but it does sound like you"


def test_short_text_confidence_is_capped():
    """Too little text to be certain, however first-person it is."""
    score, _, _ = score_text("I think I know what I mean but I really do not, I think.")
    assert score <= 0.80


def test_a_short_impersonal_list_is_still_dropped():
    _, reason, verdict = score_text("milk\neggs\nbread\ncoffee\nolive oil\nrice\n")
    assert verdict == "drop"
    assert reason == "too short to show a voice"


# --------------------------------------------------------------------------- #
# Regressions found on a fresh realistic folder
# --------------------------------------------------------------------------- #

def test_underscored_financial_filenames_are_caught():
    """`_` is a word character, so \\b rules silently missed the commonest
    separator in a saved document's name. Every separator now normalizes."""
    for name in (
        "tax-return.pdf",
        "tax_return_2024.pdf",
        "W2_2025.pdf",
        "bank_statement_march.pdf",
        "Lease_Agreement_signed.pdf",
        "2024.invoice.final.pdf",
        "utility bill march.pdf",
        "MortgageStatement.pdf",
        "paypal_receipt_0412.png",
    ):
        _, reason, verdict = score_binary(name, "application/pdf")
        assert verdict == "drop", name
        assert reason == "the file name looks like a financial or legal document"


def test_underscored_photo_filenames_are_still_kept():
    for name in ("IMG_4821.png", "IMG-4821.png", "img4821.png",
                 "Screenshot_2026-03-04.png", "my_journal_1997.pdf",
                 "handwritten_note_scan.jpg"):
        _, _, verdict = score_binary(name, "image/png")
        assert verdict == "keep", name


def test_normalize_name_splits_every_separator():
    assert relevance._normalize_name("tax_return_2024.pdf") == "tax return 2024"
    assert relevance._normalize_name("Lease-Agreement.PDF") == "lease agreement"
    assert relevance._normalize_name("MortgageStatement.pdf") == "mortgage statement"
    assert relevance._normalize_name("IMG_4821.png") == "img 4821"


def test_a_financial_text_filename_only_nudges_and_never_decides():
    """The same tokenizer, applied to text, must not override what we read."""
    _, _, verdict = score_text(ESSAY_ABOUT_MONEY, origin="tax_return_2024.txt")
    assert verdict != "drop"


def test_a_short_genuine_reply_survives_its_quoted_chain():
    """The whole point of stripping rather than dropping.

    strip_quoted returns the user's own two sentences; a second length floor in
    triage used to throw them away as "mostly a quoted reply".
    """
    reply = (
        "Subject: Re: the draft\n"
        "\n"
        "Honestly I think the second half is stronger. Cut the opening and start\n"
        "where it gets difficult. That's where you sound like yourself.\n"
        "\n"
        "On Tue, Mar 4, 2025 at 9:12 AM, Sam wrote:\n"
        + "> As discussed, please find the revised draft attached for review.\n" * 8
    )
    kept, rejected = triage([sample("re-draft.eml", reply)], [])
    assert [i.origin for i in kept] == ["re-draft.eml"], (
        f"dropped as: {rejected[0].reason if rejected else ''}"
    )
    kept_reply = kept[0]
    assert kept_reply.verdict != "drop"
    assert "Honestly I think the second half" in kept_reply.sample.text
    assert "please find the revised draft" not in kept_reply.sample.text
    assert kept_reply.reason != "mostly a quoted reply from someone else"


def test_a_very_short_reply_above_the_keep_threshold_is_simply_kept():
    reply = (
        "Yes please, I would love that. I'm free after four on Thursday and I\n"
        "honestly cannot wait to see it.\n"
        "\n"
        "On Tue, Mar 4, 2025 at 9:12 AM, Sam wrote:\n"
        + "> Let me know if you would like to see the space before you decide.\n" * 8
    )
    kept, _ = triage([sample("yes.eml", reply)], [])
    assert len(kept) == 1
    assert kept[0].verdict in {"keep", "unsure"}


def test_an_unknown_pdf_is_rejected_so_the_user_opts_in():
    """We cannot read it, so the safe default is to make the user ask for it."""
    files = [("scan001.pdf", "application/pdf", b"%PDF")]
    kept, rejected = triage([], files)
    assert not kept
    assert [i.origin for i in rejected] == ["scan001.pdf"]
    assert rejected[0].verdict == "unsure"
    assert rejected[0].reason == "a pdf we cannot check without sending it"


def test_an_unsure_text_sample_is_still_kept():
    """The asymmetry is deliberate: we read the text, we cannot read the pdf."""
    kept, _ = triage([sample("resume.txt", RESUME)], [])
    assert len(kept) == 1
    assert kept[0].verdict == "unsure"
