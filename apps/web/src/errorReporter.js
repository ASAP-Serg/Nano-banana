/** Lightweight browser → API error reporter (deduped, no loops). */

const ENDPOINT = "/api/v1/client-errors";
const DEDUPE_MS = 15_000;
const MAX_QUEUE = 20;

const seen = new Map();
let queue = [];
let flushing = false;

function fingerprint(payload) {
  return [payload.source, payload.status || "", payload.path || "", payload.message || ""]
    .join("|")
    .slice(0, 300);
}

function shouldSend(payload) {
  const key = fingerprint(payload);
  const now = Date.now();
  const prev = seen.get(key) || 0;
  if (now - prev < DEDUPE_MS) return false;
  seen.set(key, now);
  if (seen.size > 200) {
    for (const [k, t] of seen) {
      if (now - t > DEDUPE_MS * 4) seen.delete(k);
    }
  }
  return true;
}

function enqueue(payload) {
  if (!shouldSend(payload)) return;
  queue.push(payload);
  if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);
  flush();
}

async function flush() {
  if (flushing || !queue.length) return;
  flushing = true;
  try {
    while (queue.length) {
      const body = queue.shift();
      try {
        await fetch(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify(body),
          keepalive: true,
        });
      } catch {
        /* swallow — never recurse into reporter */
      }
    }
  } finally {
    flushing = false;
  }
}

function base(extra = {}) {
  return {
    url: typeof location !== "undefined" ? String(location.href).slice(0, 500) : "",
    user_agent: typeof navigator !== "undefined" ? String(navigator.userAgent || "").slice(0, 300) : "",
    ...extra,
  };
}

export function reportError(err, source = "error", extra = {}) {
  const message =
    (err && (err.message || err.reason || String(err))) ||
    (typeof err === "string" ? err : "unknown");
  const stack = (err && err.stack) || "";
  enqueue(
    base({
      source,
      message: String(message).slice(0, 800),
      stack: String(stack).slice(0, 4000),
      path: extra.path || "",
      status: extra.status ?? null,
    })
  );
}

export function reportApiFailure(path, status, detail) {
  // Skip auth noise — session expiry is expected; don't flood.
  if (status === 401 || status === 403) return;
  if (path && String(path).includes("/client-errors")) return;
  enqueue(
    base({
      source: "api",
      message: String(detail || `HTTP ${status}`).slice(0, 800),
      path: String(path || "").slice(0, 300),
      status: status || null,
      stack: "",
    })
  );
}

export function installErrorReporter() {
  if (typeof window === "undefined") return;
  if (window.__nbErrorReporterInstalled) return;
  window.__nbErrorReporterInstalled = true;

  window.addEventListener("error", (ev) => {
    reportError(ev.error || ev.message, "error");
  });
  window.addEventListener("unhandledrejection", (ev) => {
    reportError(ev.reason || "unhandledrejection", "unhandledrejection");
  });
}
