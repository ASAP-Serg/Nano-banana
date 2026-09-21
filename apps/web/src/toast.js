export function toast(message, type = "success") {
  const el = document.getElementById("nb-toast");
  if (!el) return;
  el.className = `alert alert-${type === "error" ? "danger" : type} position-fixed bottom-0 end-0 m-3`;
  el.textContent = message;
  el.style.display = "block";
  el.style.zIndex = "1080";
  window.clearTimeout(el._hide);
  el._hide = window.setTimeout(() => {
    el.style.display = "none";
  }, 3500);
}

export async function downloadImage(imageUrl, prompt) {
  try {
    const response = await fetch(imageUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const sanitized = (prompt || "image")
      .substring(0, 50)
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .replace(/\s+/g, "_")
      .toLowerCase();
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[:-]/g, "").replace("T", "_");
    a.download = `nano_banana_${sanitized}_${timestamp}.jpg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    toast("Изображение скачано");
  } catch (err) {
    window.open(imageUrl, "_blank", "noopener,noreferrer");
    toast(err.message || "Открыли изображение в новой вкладке", "error");
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
