export async function copyText(text, label = "ID") {
  try {
    await navigator.clipboard.writeText(String(text));
    toast(`${label} скопирован`);
  } catch {
    toast("Не удалось скопировать", "error");
  }
}

/** Format seconds for gallery cards: 12.4 с / 1 мин 5 с */
export function formatDurationSeconds(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) return null;
  if (n < 60) {
    const rounded = Math.round(n * 10) / 10;
    return `${String(rounded).replace(/\.0$/, "")} с`;
  }
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return `${m} мин ${s} с`;
}

export function formatUsd(n) {
  const value = Number(n);
  if (!Number.isFinite(value)) return null;
  return `$${value.toFixed(5)}`;
}

export function shortJobId(id) {
  const value = String(id || "");
  if (value.length <= 20) return value;
  return `${value.slice(0, 8)}…${value.slice(-4)}`;
}

export function toast(message, type = "success") {
  const el = document.getElementById("nb-toast");
  if (!el) return;
  el.className = `alert alert-${type === "error" ? "danger" : type} position-fixed bottom-0 end-0 m-3`;
  el.textContent = message;
  el.style.display = "block";
  el.style.zIndex = "4000";
  window.clearTimeout(el._hide);
  el._hide = window.setTimeout(() => {
    el.style.display = "none";
  }, 3500);
}

export function isSafeMediaUrl(url) {
  if (!url || typeof url !== "string") return false;
  const value = url.trim();
  if (!value || value.includes("..")) return false;
  try {
    const parsed = new URL(value, window.location.origin);
    if (parsed.origin !== window.location.origin) return false;
    return /^\/api\/v1\/images\/\d+\/(file|reference\/\d+)\/?$/.test(parsed.pathname);
  } catch {
    return false;
  }
}

function downloadFileUrl(imageUrl) {
  try {
    const u = new URL(imageUrl, window.location.origin);
    if (/^\/api\/v1\/images\/\d+\/file\/?$/.test(u.pathname)) {
      u.searchParams.set("download", "1");
      return `${u.pathname}${u.search}`;
    }
  } catch {
    /* fall through */
  }
  return imageUrl;
}

function downloadFilename(prompt) {
  const sanitized = (prompt || "image")
    .substring(0, 50)
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "_")
    .toLowerCase();
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[:-]/g, "").replace("T", "_");
  return `nano_banana_${sanitized}_${timestamp}.jpg`;
}

function triggerBlobDownload(blob, prompt) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = downloadFilename(prompt);
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

async function blobFromCdn(cdnUrl) {
  const response = await fetch(cdnUrl, {
    credentials: "omit",
    mode: "cors",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.blob();
}

export async function downloadImage(imageUrl, prompt) {
  if (!isSafeMediaUrl(imageUrl)) {
    toast("Некорректная ссылка на изображение", "error");
    return;
  }
  try {
    // Auth on our /file?download=1: MinIO bytes, or JSON {url} for Moonez CDN.
    const response = await fetch(downloadFileUrl(imageUrl), {
      credentials: "include",
      headers: { Accept: "application/json,image/*,*/*" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    let blob;
    if (contentType.includes("application/json")) {
      const payload = await response.json();
      const cdnUrl = typeof payload?.url === "string" ? payload.url : "";
      if (!/^https?:\/\//i.test(cdnUrl)) {
        throw new Error(payload?.hint || "Нет ссылки на файл");
      }
      try {
        blob = await blobFromCdn(cdnUrl);
      } catch (cdnErr) {
        // Wiki jam: net::ERR_CONNECTION_RESET to cdn.rendergrid.io — browser
        // cannot reach Moonez CDN. Popup after await is often blocked too.
        try {
          const { reportError } = await import("./errorReporter.js");
          reportError(cdnErr, "download-cdn", { path: cdnUrl.slice(0, 300) });
        } catch {
          /* ignore */
        }
        throw new Error(
          "CDN Moonez недоступен из вашей сети. Подождите 20–40 сек (файл сохранится у нас) и нажмите «Скачать» ещё раз."
        );
      }
    } else {
      blob = await response.blob();
    }
    triggerBlobDownload(blob, prompt);
    toast("Изображение скачано");
  } catch (err) {
    try {
      const { reportError } = await import("./errorReporter.js");
      reportError(err, "download", { path: String(imageUrl || "").slice(0, 300) });
    } catch {
      /* ignore */
    }
    toast(err.message || "Не удалось скачать изображение", "error");
  }
}

export function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export const ASPECTS = [
  ["1:1", "1:1", "/icons/aspect-1-1.svg"],
  ["16:9", "16:9", "/icons/aspect-16-9.svg"],
  ["9:16", "9:16", "/icons/aspect-9-16.svg"],
  ["4:3", "4:3", "/icons/aspect-4-3.svg"],
  ["3:4", "3:4", "/icons/aspect-3-4.svg"],
  ["21:9", "21:9 ультраширокий", "/icons/aspect-21-9.svg"],
  ["5:4", "5:4", "/icons/aspect-5-4.svg"],
  ["2:3", "2:3", "/icons/aspect-2-3.svg"],
];

export const GROUP_LABELS = {
  bananalab: "Moonez (bh_)",
  replicate: "Replicate (r8_)",
  openrouter: "OpenRouter GPT (sk-or_)",
};

export const PROVIDER_BADGE = {
  bananalab: "Moonez",
  replicate: "Replicate",
  openrouter: "OpenRouter",
};
