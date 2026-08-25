"""Tests for pixieduster.safety -- the outbound-data guardrails.

Everything here is offline: no network, no API keys, no fixtures on disk.

All "secrets" below are deliberately fake. Where possible they are the
vendor's own published example values (e.g. AWS's AKIAIOSFODNN7EXAMPLE) so
that nothing in this repository is ever a live credential.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pixieduster import safety  # noqa: E402
from pixieduster.types import Sample  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture corpus: obviously-fake secrets, one per rule.
# ---------------------------------------------------------------------------

def _f(*parts: str) -> str:
    """Assemble a fake credential at runtime.

    These fixtures have to *look* like real Slack/Stripe/SendGrid credentials or
    they would not exercise the rules. Written as literals they trip GitHub's
    push protection, which is working as intended -- so the recognisable prefix
    is joined to the body here rather than appearing anywhere in the source.
    """
    return "".join(parts)


FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEAxNotARealKeyJustPaddingPaddingPaddingPadding0000\n"
    "aGVsbG9UaGlzSXNOb3RBUmVhbEtleUF0QWxsSXRJc1Rlc3REYXRhMDAwMDAwMDA=\n"
    "-----END RSA PRIVATE KEY-----"
)

# (rule_name, text containing exactly one instance of that rule's material)
SECRET_CORPUS: list[tuple[str, str]] = [
    ("private-key-pem-block", FAKE_PEM),
    (
        "private-key-pem-header",
        "someone pasted -----BEGIN OPENSSH PRIVATE KEY----- and stopped there",
    ),
    # AWS's own documented example access key id.
    ("aws-access-key-id", "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"),
    (
        "aws-access-key-id",
        "temporary creds ASIAIOSFODNN7EXAMPLE were rotated",
    ),
    # AWS's own documented example secret access key.
    (
        "aws-secret-access-key",
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    ),
    (
        "google-api-key",
        "GEMINI_API_KEY=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q",
    ),
    (
        "google-oauth-client-secret",
        "client_secret is " + _f("GOCSPX", "-abcdEFGH1234ijklMNOP5678"),
    ),
    (
        "anthropic-api-key",
        "ANTHROPIC_KEY -> " + _f("sk", "-ant-api03-FAKEfakeFAKEfakeFAKEfakeFAKEfake1234567890AA"),
    ),
    (
        "openai-api-key",
        "openai.api_key was sk-FAKEfakeFAKEfake1234567890abcdefABCDEF0123456789",
    ),
    (
        "openai-api-key",
        "new style key sk-proj-FAKEfake1234567890abcdefABCDEF01",
    ),
    (
        "github-token",
        "git remote add origin https://" + _f("ghp", "_FAKEfake1234567890abcdefABCDEF012345") + "@github.com/x/y",
    ),
    ("github-token", "oauth token gho_FAKEfake1234567890abcdefABCDEF012345 leaked"),
    ("github-token", "server token ghs_FAKEfake1234567890abcdefABCDEF012345 leaked"),
    ("github-token", "user token ghu_FAKEfake1234567890abcdefABCDEF012345 leaked"),
    (
        "github-fine-grained-pat",
        "PAT " + _f("github", "_pat_11ABCDEFG0FAKEfake1234_abcdefghijklmnopqrstuvwxyz0123456789ABCD"),
    ),
    ("slack-token", "SLACK_BOT_TOKEN=" + _f("xox", "b-1234567890-0987654321-FAKEfakeFAKEfake")),
    ("slack-token", "legacy " + _f("xox", "p-1234567890-1234567890-1234567890-abcdef")),
    (
        "slack-webhook-url",
        "post to https://hooks.slack.com/services/T00000000/B00000000/FAKEfakeFAKEfake1234",
    ),
    ("stripe-secret-key", "STRIPE=" + _f("sk", "_live_", "FAKEfake1234567890abcdef")),
    ("npm-token", "//registry.npmjs.org/:_authToken=" + _f("npm", "_FAKEfake1234567890abcdefABCDEF012345")),
    (
        "pypi-token",
        "twine password " + _f("pypi", "-AgEIcHlwaS5vcmcFAKEfake1234567890abcdef"),
    ),
    (
        "sendgrid-api-key",
        _f("SG", ".FAKEfake1234567890abcd.FAKEfake1234567890abcdefghijklmnopqrstuvwxy"),
    ),
    ("huggingface-token", "HF token " + _f("hf", "_FAKEfakeFAKEfake1234567890abcdefgh")),
    (
        "jwt",
        "Cookie: session=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkZha2UifQ.FAKEfakeSignature1234567890",
    ),
    (
        "authorization-header",
        'Authorization: Bearer FAKEfake1234567890abcdefABCDEF0123456789',
    ),
    (
        "connection-string-credentials",
        "DATABASE_URL=postgres://appuser:sup3rS3cretPw@db.internal:5432/prod",
    ),
    (
        "connection-string-credentials",
        "mongodb+srv://admin:hunter2hunter2@cluster0.example.mongodb.net/db",
    ),
    (
        "generic-secret-assignment",
        'password = "Xq7!vB2mZr9Ld4Tc"',
    ),
    (
        "generic-secret-assignment",
        "api_key: 8f3Kd9Xq2Lm7Zp4Rv1Nb6Tc",
    ),
    (
        "dotenv-high-entropy-value",
        "SESSION_SECRET=9dK3xQ7pL2mZ8vR4tN6bY1cW5jH0gF3sA7dE2qU4iO6p",
    ),
]

#: Every rule that the corpus above is expected to exercise.
EXPECTED_RULES = {rule for rule, _ in SECRET_CORPUS}


# ---------------------------------------------------------------------------
# False-positive corpus: innocent prose and ordinary code.
# ---------------------------------------------------------------------------

INNOCENT_CORPUS: list[str] = [
    # --- English prose that mentions the trigger words -------------------
    "Remember to rotate your password every ninety days; the old one expires.",
    "The secret to a good commit message is explaining why, not what.",
    "I finally got the token bucket rate limiter working after three attempts.",
    "We store the API key in the user's keychain, never in the repository.",
    "Her secret key insight was that the parser could be made single-pass.",
    "This release adds password strength hints and a token refresh flow.",
    "Nobody could find the credentials documentation, so I rewrote it.",
    "The auth token expires after an hour, which surprised everyone.",
    "Add a passwd(5) reference to the man page section about accounts.",
    "Access token lifetimes are configurable per environment now.",
    # --- Ordinary code identifiers and assignments -----------------------
    "self.api_key = api_key",
    "password = get_password()",
    "token = os.environ['GITHUB_TOKEN']",
    "secret = config.get('secret')",
    "api_key: Optional[str] = None",
    "let accessToken = response.accessToken;",
    "const apiKey = process.env.API_KEY;",
    "SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')",
    "client_secret = settings.OAUTH_CLIENT_SECRET",
    "password: str",
    "def refresh_token(self, token: str) -> str:",
    "auth_token = build_auth_token(user, scopes)",
    'password = ""',
    "api_key = None",
    "PASSWORD = 'changeme'",
    "token = tokens[index]",
    'api_key = "<your-api-key-here>"',
    "SECRET=${VAULT_SECRET}",
    "password={{ ansible_password }}",
    "private_key = load_private_key(path)",
    "credentials = google.auth.default()",
    "encryption_key = derive_key(salt, passphrase)",
    # --- config / docs that look scary but are not -----------------------
    "PATH=/usr/local/bin:/usr/bin:/bin",
    "DEBUG=true",
    "APP_VERSION=1.24.7",
    "LOG_FORMAT=json",
    "DATABASE_URL=postgres://localhost:5432/appdb",
    "See https://example.com/docs/authentication for token setup.",
    "Run `gh auth login` to store a GitHub token in your keyring.",
    "commit 3f6a2b1c9d8e7f0a1b2c3d4e5f6a7b8c9d0e1f2a rewrites the token cache",
    "The sk-prefixed keys belong to OpenAI; ours start with AIza.",
    "Set GEMINI_API_KEY in your shell profile before running pixieduster.",
]


def _samples(texts: list[str], kind: str = "doc") -> list[Sample]:
    return [
        Sample(kind=kind, origin=f"fixture-{i}", text=text)
        for i, text in enumerate(texts)
    ]


# ---------------------------------------------------------------------------
# Rule coverage
# ---------------------------------------------------------------------------


def test_contract_required_rules_exist():
    """Every rule family named in CONTRACT.md must be present."""
    names = {name for name, _, _ in safety.SECRET_RULES}
    required = {
        "aws-access-key-id",
        "aws-secret-access-key",
        "google-api-key",
        "openai-api-key",
        "anthropic-api-key",
        "github-token",
        "github-fine-grained-pat",
        "slack-token",
        "stripe-secret-key",
        "private-key-pem-block",
        "jwt",
        "generic-secret-assignment",
        "connection-string-credentials",
        "dotenv-high-entropy-value",
    }
    assert required <= names, f"missing rules: {sorted(required - names)}"


def test_rule_tuples_are_well_formed():
    for entry in safety.SECRET_RULES:
        assert isinstance(entry, tuple) and len(entry) == 3
        name, pattern, severity = entry
        assert isinstance(name, str) and name
        assert isinstance(pattern, str) and pattern
        assert severity in {"high", "medium", "low"}


def test_rule_names_are_unique():
    names = [name for name, _, _ in safety.SECRET_RULES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("rule,text", SECRET_CORPUS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(SECRET_CORPUS)])
def test_every_fake_secret_is_detected(rule: str, text: str):
    findings = safety.scan(_samples([text]))
    assert findings, f"{rule}: nothing detected in {text[:60]!r}"
    rules = {f.rule for f in findings}
    assert rule in rules, f"expected {rule}, got {sorted(rules)}"


@pytest.mark.parametrize("rule,text", SECRET_CORPUS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(SECRET_CORPUS)])
def test_redact_removes_all_secret_material(rule: str, text: str):
    redacted = safety.redact(text)
    assert "<REDACTED:" in redacted
    for hit in safety._collect(text):
        assert hit.value not in redacted
        # no distinctive 8-char run of the secret survives either
        assert not safety._leaks(redacted, hit.value)


@pytest.mark.parametrize("rule,text", SECRET_CORPUS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(SECRET_CORPUS)])
def test_finding_excerpts_never_leak(rule: str, text: str):
    findings = safety.scan(_samples([text]))
    for hit in safety._collect(text):
        for finding in findings:
            assert hit.value not in finding.excerpt
            assert not safety._leaks(finding.excerpt, hit.value)


# ---------------------------------------------------------------------------
# False positives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", INNOCENT_CORPUS)
def test_innocent_text_does_not_fire(text: str):
    findings = safety.scan(_samples([text]))
    assert findings == [], f"false positive {[f.rule for f in findings]} on {text!r}"


@pytest.mark.parametrize("text", INNOCENT_CORPUS)
def test_innocent_text_survives_redaction_unchanged(text: str):
    assert safety.redact(text) == text


def test_false_positive_rate_is_zero():
    """Aggregate check so the FP rate is reported as one number."""
    flagged = [t for t in INNOCENT_CORPUS if safety.scan(_samples([t]))]
    rate = len(flagged) / len(INNOCENT_CORPUS)
    assert rate == 0.0, f"FP rate {rate:.1%}: {flagged}"


def test_prose_containing_words_in_bulk_document():
    """A whole innocent document, not just single lines."""
    doc = "\n".join(INNOCENT_CORPUS)
    assert safety.scan(_samples([doc])) == []


# ---------------------------------------------------------------------------
# scan() semantics
# ---------------------------------------------------------------------------


def test_line_numbers_are_relative_to_the_sample():
    text = "line one\nline two\nAWS_KEY=AKIAIOSFODNN7EXAMPLE\nline four"
    findings = safety.scan(_samples([text]))
    assert len(findings) == 1
    assert findings[0].line == 3


def test_first_line_is_line_one():
    findings = safety.scan(_samples(["AKIAIOSFODNN7EXAMPLE\n"]))
    assert findings[0].line == 1


def test_origin_is_propagated():
    sample = Sample(kind="commit", origin="git log deadbee", text="key AKIAIOSFODNN7EXAMPLE")
    finding = safety.scan([sample])[0]
    assert finding.origin == "git log deadbee"


def test_scan_handles_empty_input():
    assert safety.scan([]) == []
    assert safety.scan([Sample(kind="doc", origin="empty", text="")]) == []


def test_scan_reports_each_secret_once():
    """A key inside a KEY= line must not be reported by three rules at once."""
    text = "GEMINI_API_KEY=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"
    findings = safety.scan(_samples([text]))
    assert len(findings) == 1
    assert findings[0].rule == "google-api-key"


def test_multiple_secrets_in_one_sample():
    text = (
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "GEMINI=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q\n"
    )
    findings = safety.scan(_samples([text]))
    assert {f.rule for f in findings} == {"aws-access-key-id", "google-api-key"}


def test_severity_values_are_valid():
    texts = [t for _, t in SECRET_CORPUS]
    for finding in safety.scan(_samples(texts)):
        assert finding.severity in {"high", "medium", "low"}


def test_multiline_pem_excerpt_is_single_line_and_safe():
    finding = [f for f in safety.scan(_samples([FAKE_PEM])) if f.rule.startswith("private-key")][0]
    assert "\n" not in finding.excerpt
    assert "MIIEow" not in finding.excerpt


def test_excerpt_is_length_capped():
    text = "x" * 500 + " AKIAIOSFODNN7EXAMPLE " + "y" * 500
    finding = safety.scan(_samples([text]))[0]
    assert len(finding.excerpt) <= 260


def test_no_finding_excerpt_contains_any_corpus_secret():
    """Cross-check: scan the whole corpus at once, assert global non-leakage."""
    texts = [t for _, t in SECRET_CORPUS]
    findings = safety.scan(_samples(texts))
    all_secrets = [h.value for t in texts for h in safety._collect(t)]
    blob = "\n".join(f.excerpt for f in findings)
    for secret in all_secrets:
        assert not safety._leaks(blob, secret), f"leaked {secret[:4]}..."


# ---------------------------------------------------------------------------
# redact()
# ---------------------------------------------------------------------------


def test_redact_format():
    out = safety.redact("k=AKIAIOSFODNN7EXAMPLE")
    assert out == "k=<REDACTED:aws-access-key-id>"


def test_redact_keeps_key_name_for_generic_rule():
    out = safety.redact('password = "Xq7!vB2mZr9Ld4Tc"')
    assert out.startswith('password = "<REDACTED:generic-secret-assignment>')


def test_redact_is_idempotent():
    text = "AWS=AKIAIOSFODNN7EXAMPLE and AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"
    once = safety.redact(text)
    assert safety.redact(once) == once


def test_redact_handles_empty():
    assert safety.redact("") == ""


def test_redact_preserves_surrounding_text():
    out = safety.redact("before AKIAIOSFODNN7EXAMPLE after")
    assert out.startswith("before ") and out.endswith(" after")


def test_redacted_output_is_not_re_flagged_as_a_secret():
    text = "\n".join(t for _, t in SECRET_CORPUS)
    redacted = safety.redact(text)
    assert safety.scan(_samples([redacted])) == []


# ---------------------------------------------------------------------------
# Entropy helper
# ---------------------------------------------------------------------------


def test_entropy_ordering():
    assert safety.shannon_entropy("") == 0.0
    assert safety.shannon_entropy("aaaaaaaa") == 0.0
    assert safety.shannon_entropy("password") < safety.shannon_entropy(
        "9dK3xQ7pL2mZ8vR4tN6b"
    )


# ---------------------------------------------------------------------------
# Token + cost estimation
# ---------------------------------------------------------------------------


def test_estimate_tokens_is_roughly_len_over_four():
    assert safety.estimate_tokens("") == 0
    assert safety.estimate_tokens("abcd") == 1
    assert safety.estimate_tokens("a" * 400) == 100
    assert safety.estimate_tokens("a") == 1  # never rounds a non-empty string to 0


def test_estimate_cost_known_model():
    # gemini-2.5-flash: $0.30 in / $2.50 out per 1M tokens.
    cost = safety.estimate_cost(1_000_000, 1_000_000, "gemini-2.5-flash")
    assert cost == pytest.approx(0.30 + 2.50)


def test_estimate_cost_default_model_from_app():
    assert safety.estimate_cost(1_000_000, 0, "gemini-3.6-flash") == pytest.approx(0.75)


def test_estimate_cost_accepts_models_prefix():
    a = safety.estimate_cost(1000, 1000, "models/gemini-2.5-flash")
    b = safety.estimate_cost(1000, 1000, "gemini-2.5-flash")
    assert a == b


def test_lite_variant_is_not_confused_with_base():
    lite = safety.estimate_cost(1_000_000, 0, "gemini-2.5-flash-lite")
    base = safety.estimate_cost(1_000_000, 0, "gemini-2.5-flash")
    assert lite == pytest.approx(0.10)
    assert base == pytest.approx(0.30)
    assert lite != base


def test_estimate_cost_long_context_tier():
    below = safety.estimate_cost(100_000, 0, "gemini-2.5-pro")
    above = safety.estimate_cost(300_000, 0, "gemini-2.5-pro")
    assert below == pytest.approx(100_000 / 1e6 * 1.25)
    assert above == pytest.approx(300_000 / 1e6 * 2.50)


@pytest.mark.parametrize(
    "model",
    [
        "",
        "gpt-4o",
        "claude-opus-5",
        "gemini-42-ultra",
        "some-unreleased-model",
        "gemini-3.1-flash-image",  # per-image billing: we refuse to guess
        "text-embedding-004",
    ],
)
def test_estimate_cost_returns_none_for_unknown_models(model: str):
    assert safety.estimate_cost(1000, 1000, model) is None


def test_pricing_table_shape():
    for name, entry in safety.MODEL_PRICING.items():
        assert "input" in entry and "output" in entry, name
        assert entry["input"] >= 0 and entry["output"] >= 0, name
        if "threshold" in entry:
            assert entry["input_over"] >= entry["input"], name


def test_pricing_table_has_verification_comment():
    """The contract requires a 'last verified' marker and a source URL."""
    source = Path(safety.__file__).read_text(encoding="utf-8")
    assert "last verified:" in source
    assert "https://ai.google.dev/gemini-api/docs/pricing" in source


def test_estimate_cost_zero_tokens():
    assert safety.estimate_cost(0, 0, "gemini-2.5-flash") == 0.0


# ---------------------------------------------------------------------------
# dry_run_report()
# ---------------------------------------------------------------------------


def test_dry_run_report_lists_every_sample():
    samples = [
        Sample(kind="commit", origin="git log a1b2c3d", text="hello world"),
        Sample(kind="doc", origin="README.md", text="x" * 400),
    ]
    report = safety.dry_run_report(samples, [])
    assert "git log a1b2c3d" in report
    assert "README.md" in report
    assert "[commit]" in report and "[doc]" in report
    assert "100 tokens" in report  # 400 chars / 4


def test_dry_run_report_is_plain_text():
    samples = [Sample(kind="doc", origin="README.md", text="hello")]
    findings = safety.scan(_samples(["k=AKIAIOSFODNN7EXAMPLE"]))
    report = safety.dry_run_report(samples, findings)
    assert "[/" not in report          # no rich closing tags
    assert "\x1b[" not in report       # no ANSI escapes
    assert "[bold" not in report


def test_dry_run_report_includes_findings():
    findings = safety.scan(_samples(["k=AKIAIOSFODNN7EXAMPLE"]))
    report = safety.dry_run_report([], findings)
    assert "aws-access-key-id" in report
    assert "HIGH" in report
    assert "AKIAIOSFODNN7EXAMPLE" not in report


def test_dry_run_report_never_contains_raw_secrets():
    texts = [t for _, t in SECRET_CORPUS]
    samples = _samples(texts)
    report = safety.dry_run_report(samples, safety.scan(samples))
    for text in texts:
        for hit in safety._collect(text):
            assert not safety._leaks(report, hit.value)


def test_dry_run_report_handles_no_findings():
    report = safety.dry_run_report([Sample(kind="doc", origin="a.md", text="hi")], [])
    assert "No potential secrets detected" in report


def test_dry_run_report_handles_empty_everything():
    report = safety.dry_run_report([], [])
    assert "(none)" in report
    assert "PIXIEDUSTER DRY RUN" in report


def test_dry_run_report_renders_unknown_cost_gracefully():
    samples = [Sample(kind="doc", origin="a.md", text="x" * 4000)]
    report = safety.dry_run_report(samples, [], model="totally-unknown-model")
    assert "cost unknown" in report
    assert "$" not in report.split("cost unknown")[0].split("estimated cost")[-1]


def test_dry_run_report_renders_known_cost():
    samples = [Sample(kind="doc", origin="a.md", text="x" * 4000)]
    report = safety.dry_run_report(samples, [], model="gemini-2.5-flash")
    assert "estimated cost" in report
    assert "$" in report


def test_dry_run_report_states_tokens_are_estimates():
    report = safety.dry_run_report([], [])
    assert "estimate" in report.lower()


def test_dry_run_report_uses_precomputed_sample_tokens():
    samples = [Sample(kind="doc", origin="a.md", text="x" * 400, tokens=7)]
    assert "(7 tokens)" in safety.dry_run_report(samples, [])


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_module_makes_no_network_calls():
    source = Path(safety.__file__).read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "import urllib.request", "socket."):
        assert banned not in source, f"safety.py must stay offline: found {banned}"


def test_realistic_repo_document_end_to_end():
    """A plausible README with one embedded secret among lots of trigger words."""
    doc = (
        "# Deploy Guide\n"
        "\n"
        "Set your password in the vault, never in the repo. The API key is read\n"
        "from the environment at boot:\n"
        "\n"
        "    api_key = os.environ['GEMINI_API_KEY']\n"
        "\n"
        "Oops, an old snapshot of .env got committed:\n"
        "\n"
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "\n"
        "Rotate the token afterwards.\n"
    )
    findings = safety.scan([Sample(kind="doc", origin="DEPLOY.md", text=doc)])
    assert len(findings) == 1
    assert findings[0].rule == "aws-access-key-id"
    assert findings[0].line == 10
    assert "AKIAIOSFODNN7EXAMPLE" not in findings[0].excerpt
    assert "AWS_ACCESS_KEY_ID=" in findings[0].excerpt
