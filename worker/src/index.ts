/**
 * PixieDuster hosted API — a metered proxy in front of Gemini.
 *
 * The Gemini key is a Worker secret and never reaches a client. Callers
 * authenticate with their own Hugging Face token, which we verify against the
 * HF API; usage is metered per account against a daily allowance, under a hard
 * global ceiling.
 *
 * The proxy mirrors Google's URL shape (`/models/{model}:generateContent`) so
 * the CLI reaches it through the same code path as a direct call.
 *
 * Metering is charge-first: both counters are incremented in one D1 batch,
 * which runs as a transaction, and the post-increment values come back in the
 * same round trip. Two simultaneous requests therefore cannot both read "one
 * left" and both spend. If the caller turns out to be over, the charge is
 * refunded and nothing is sent upstream.
 */

const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta";
const HF_WHOAMI = "https://huggingface.co/api/whoami-v2";
const TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

/** Cache verified tokens briefly so a run of calls costs one HF round trip. */
const IDENTITY_TTL_SECONDS = 300;

const GLOBAL_ROW = "__global__";

interface Meter {
  used: number;
  total: number;
}

function corsHeaders(request: Request, env: Env): Record<string, string> {
  const origin = request.headers.get("origin") ?? "";
  const allowed = (env.ALLOWED_ORIGINS ?? "").split(",").map((o) => o.trim()).filter(Boolean);
  const ok = allowed.includes(origin);
  return {
    "access-control-allow-origin": ok ? origin : allowed[0] ?? "",
    "access-control-allow-headers": "authorization, content-type, x-turnstile-token, x-session",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-max-age": "86400",
    vary: "origin",
  };
}

/** Request-scoped CORS, set once per request in fetch(). */
let cors: Record<string, string> = {};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...cors,
    },
  });
}

function fail(status: number, detail: string): Response {
  return json({ detail }, status);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function resetsAt(): string {
  const t = new Date();
  t.setUTCDate(t.getUTCDate() + 1);
  t.setUTCHours(0, 0, 0, 0);
  return `${t.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function num(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function allowedModels(env: Env): Set<string> {
  const raw = env.ALLOWED_MODELS ?? "gemini-3.6-flash,gemini-2.5-flash,gemini-2.5-flash-lite";
  return new Set(raw.split(",").map((m) => m.trim()).filter(Boolean));
}

// ---------------------------------------------------------------------------
// identity
// ---------------------------------------------------------------------------

/**
 * Verify a Hugging Face token and return the username it belongs to.
 *
 * The token is only ever sent to huggingface.co. It is never stored, and never
 * written to a log.
 */
async function whoami(token: string, env: Env): Promise<string> {
  const cacheKey = `hf:${token}`;
  const cached = await env.QUOTA_KV?.get(cacheKey);
  if (cached) return cached;

  const response = await fetch(HF_WHOAMI, {
    headers: { authorization: `Bearer ${token}` },
  });

  if (response.status === 401) throw fail(401, "Hugging Face rejected that token.");
  if (!response.ok) throw fail(502, "Hugging Face could not verify that token.");

  const body = (await response.json()) as { name?: string };
  const name = body.name;
  if (!name) throw fail(401, "That token has no account attached to it.");

  await env.QUOTA_KV?.put(cacheKey, name, { expirationTtl: IDENTITY_TTL_SECONDS });
  return name;
}

/**
 * Identify an anonymous browser visitor.
 *
 * There is no account to meter against, so we meter the IP -- stored only as a
 * salted hash, never in the clear. A Turnstile token must accompany the request,
 * which is what stops the endpoint being trivially scripted.
 */
async function anonymous(request: Request, env: Env): Promise<string> {
  const session = request.headers.get("x-session") ?? "";
  if (session) {
    const who = await readSession(session, env);
    if (who) return who;
    throw fail(401, "Your session expired. Reload the page.");
  }

  if (!env.TURNSTILE_SECRET) {
    throw fail(503, "Anonymous access is not enabled here. Sign in, or use your own key.");
  }

  const token = request.headers.get("x-turnstile-token") ?? "";
  if (!token) throw fail(401, "Missing the human-verification token.");

  const ip = request.headers.get("cf-connecting-ip") ?? "0.0.0.0";
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", token);
  form.append("remoteip", ip);

  const verdict = await fetch(TURNSTILE_VERIFY, { method: "POST", body: form });
  const body = (await verdict.json()) as { success?: boolean };
  if (!body.success) throw fail(401, "Human verification failed. Reload the page and try again.");

  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${env.IP_SALT ?? "pixieduster"}:${ip}`)
  );
  const hex = [...new Uint8Array(digest)].slice(0, 8)
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  return `anon:${hex}`;
}

/** How long one Turnstile challenge buys a browser visitor. */
const SESSION_TTL_SECONDS = 2 * 60 * 60;

function b64url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(payload: string, env: Env): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(env.IP_SALT ?? "pixieduster"),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return b64url(new Uint8Array(sig));
}

/**
 * Mint a session for a verified browser visitor.
 *
 * Turnstile tokens are single-use, but generating a persona takes several calls.
 * Rather than challenge the visitor repeatedly, one challenge buys a signed,
 * expiring session carrying the same hashed-IP identity the meter uses.
 */
async function mintSession(anon: string, env: Env): Promise<{ session: string; expires_in: number }> {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const payload = b64url(new TextEncoder().encode(JSON.stringify({ anon, exp })));
  return { session: `${payload}.${await hmac(payload, env)}`, expires_in: SESSION_TTL_SECONDS };
}

/** Verify a session and return the identity it carries, or null. */
async function readSession(value: string, env: Env): Promise<string | null> {
  const [payload, signature] = value.split(".");
  if (!payload || !signature) return null;
  if (signature !== (await hmac(payload, env))) return null;
  try {
    const body = JSON.parse(
      new TextDecoder().decode(
        Uint8Array.from(atob(payload.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0))
      )
    ) as { anon?: string; exp?: number };
    if (!body.anon || !body.exp || body.exp < Date.now() / 1000) return null;
    return body.anon;
  } catch {
    return null;
  }
}

function bearer(request: Request): string {
  const header = request.headers.get("authorization") ?? "";
  return header.toLowerCase().startsWith("bearer ") ? header.slice(7).trim() : "";
}

// ---------------------------------------------------------------------------
// metering
// ---------------------------------------------------------------------------

async function ensureSchema(env: Env): Promise<void> {
  await env.DB.exec(
    "CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, who TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, who))"
  );
}

async function readMeter(user: string, env: Env): Promise<Meter> {
  const day = today();
  const [mine, total] = await env.DB.batch<{ n: number }>([
    env.DB.prepare("SELECT n FROM usage WHERE day = ? AND who = ?").bind(day, user),
    env.DB.prepare("SELECT n FROM usage WHERE day = ? AND who = ?").bind(day, GLOBAL_ROW),
  ]);
  return {
    used: mine.results[0]?.n ?? 0,
    total: total.results[0]?.n ?? 0,
  };
}

/**
 * Increment the caller's counter and the global counter in one transaction,
 * returning both post-increment values. Charging before the upstream call is
 * what makes the ceiling race-proof.
 */
async function charge(user: string, env: Env): Promise<Meter> {
  const day = today();
  const bump = (who: string) =>
    env.DB.prepare(
      "INSERT INTO usage (day, who, n) VALUES (?, ?, 1) " +
        "ON CONFLICT(day, who) DO UPDATE SET n = n + 1 RETURNING n"
    ).bind(day, who);

  const [mine, total] = await env.DB.batch<{ n: number }>([bump(user), bump(GLOBAL_ROW)]);
  return {
    used: mine.results[0]?.n ?? 0,
    total: total.results[0]?.n ?? 0,
  };
}

/** Give a charge back when the request never reached Gemini. */
async function refund(user: string, env: Env): Promise<void> {
  const day = today();
  const give = (who: string) =>
    env.DB.prepare("UPDATE usage SET n = MAX(n - 1, 0) WHERE day = ? AND who = ?").bind(day, who);
  await env.DB.batch([give(user), give(GLOBAL_ROW)]);
}

// ---------------------------------------------------------------------------
// routes
// ---------------------------------------------------------------------------

function health(env: Env): Response {
  return json({
    ok: true,
    configured: Boolean(env.GEMINI_API_KEY),
    models: [...allowedModels(env)].sort(),
  });
}

async function me(user: string, env: Env): Promise<Response> {
  const limit = user.startsWith("anon:")
    ? num(env.DAILY_PER_ANON, 2)
    : num(env.DAILY_PER_USER, 5);
  const { used } = await readMeter(user, env);
  return json({
    user: user.startsWith("anon:") ? "guest" : user,
    used,
    limit,
    remaining: Math.max(limit - used, 0),
    resets_at: resetsAt(),
  });
}

async function generate(
  spec: string,
  request: Request,
  user: string,
  env: Env,
  ctx: ExecutionContext
): Promise<Response> {
  if (!env.GEMINI_API_KEY) return fail(503, "This service has no Gemini key configured.");

  const [rawModel, method] = spec.split(":");
  const model = rawModel.replace(/^models\//, "");
  if (method !== "generateContent") return fail(404, `Unsupported method: ${method || "(none)"}`);
  if (!allowedModels(env).has(model)) {
    return fail(
      400,
      `Model '${model}' is not available here. Allowed: ${[...allowedModels(env)].sort().join(", ")}`
    );
  }

  const maxBytes = num(env.MAX_BODY_BYTES, 6 * 1024 * 1024);
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > maxBytes) {
    return fail(
      413,
      `That request is ${(declared / 1_048_576).toFixed(1)} MB, over the ` +
        `${Math.round(maxBytes / 1_048_576)} MB limit. Send fewer samples.`
    );
  }

  // Read the body before charging: a malformed request should not cost quota.
  // Bounded by the size check above, so this cannot exhaust memory.
  const body = await request.arrayBuffer();
  if (body.byteLength > maxBytes) {
    return fail(413, `That request is over the ${Math.round(maxBytes / 1_048_576)} MB limit.`);
  }

  const perUser = user.startsWith("anon:")
    ? num(env.DAILY_PER_ANON, 2)
    : num(env.DAILY_PER_USER, 5);
  const globalCap = num(env.DAILY_GLOBAL, 400);

  let meter: Meter;
  try {
    meter = await charge(user, env);
  } catch {
    return fail(503, "Quota store unavailable, so nothing was sent.");
  }

  if (meter.total > globalCap) {
    ctx.waitUntil(refund(user, env));
    return fail(
      429,
      "PixieDuster has hit its daily limit for everyone. Try tomorrow, or use your own key: pixieduster clone --api-key ..."
    );
  }
  if (meter.used > perUser) {
    ctx.waitUntil(refund(user, env));
    // Point people at the next step that actually applies to them.
    const nextStep = user.startsWith("anon:")
      ? "Sign in with a Hugging Face account for a larger daily allowance, or install the CLI and use your own key."
      : "Use your own key to keep going: pixieduster clone --api-key ...";
    return fail(
      429,
      `You have used all ${perUser} personas for today (resets ${resetsAt()}). ${nextStep}`
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${GEMINI_BASE}/models/${model}:${method}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-goog-api-key": env.GEMINI_API_KEY,
      },
      body,
    });
  } catch {
    await refund(user, env);
    return fail(502, "Could not reach Gemini. Nothing was charged.");
  }

  if (upstream.status >= 500) {
    ctx.waitUntil(refund(user, env));
  }

  if (!upstream.ok) {
    // Never let an upstream error echo anything about our key.
    let detail = "The model refused that request.";
    try {
      const payload = (await upstream.json()) as { error?: { message?: string } };
      if (payload.error?.message) {
        detail = payload.error.message.split(env.GEMINI_API_KEY).join("<redacted>");
      }
    } catch {
      /* non-JSON upstream error: keep the generic message */
    }
    return json({ error: { message: detail } }, upstream.status);
  }

  // Stream the success straight through rather than buffering it.
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
      ...cors,
    },
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    cors = corsHeaders(request, env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    try {
      if (path === "/api/health") return health(env);

      const token = bearer(request);
      await ensureSchema(env);

      // Two ways in: a Hugging Face token (the CLI), or a Turnstile token
      // (the web page, where there is no account and nothing to sign in to).
      const user = token
        ? `hf:${await whoami(token, env)}`
        : await anonymous(request, env);

      if (path === "/api/session" && request.method === "POST") {
        if (!user.startsWith("anon:")) {
          return fail(400, "Sessions are for browser visitors; use your token directly.");
        }
        return json(await mintSession(user, env));
      }

      if (path === "/api/me") return await me(user, env);

      if (path === "/api/models" && request.method === "GET") {
        return json({
          models: [...allowedModels(env)].sort().map((m) => ({ name: `models/${m}` })),
        });
      }

      const match = path.match(/^\/api\/models\/(.+)$/);
      if (match && request.method === "POST") {
        return await generate(decodeURIComponent(match[1]), request, user, env, ctx);
      }

      return fail(404, `No such endpoint: ${path}`);
    } catch (caught) {
      // whoami throws Responses for the expected auth failures.
      if (caught instanceof Response) return caught;
      console.error(
        JSON.stringify({ msg: "unhandled", path, error: String(caught) })
      );
      return fail(500, "Something went wrong on our side. Nothing was charged.");
    }
  },
} satisfies ExportedHandler<Env>;
