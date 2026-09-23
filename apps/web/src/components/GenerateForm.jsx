import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { ASPECTS, GROUP_LABELS, PROVIDER_BADGE, fileToDataUrl, toast } from "../toast.js";

const GROUP_ORDER = ["bananalab", "replicate", "openrouter"];

function modelHasKey(meta, keys) {
  const ready = typeof keys?.has_bananalab_key === "boolean";
  if (!ready) return meta?.available !== false;
  const flag = {
    bananalab: Boolean(keys.has_bananalab_key),
    replicate: Boolean(keys.has_replicate_key),
    openrouter: Boolean(keys.has_openrouter_key),
  };
  const providers = meta?.providers || [];
  if (!providers.length) return flag.bananalab || flag.replicate || flag.openrouter;
  return providers.some((provider) => flag[provider]);
}

async function collectImageFiles(fileList) {
  const next = [];
  for (const file of fileList) {
    if (!file.type?.startsWith("image/")) continue;
    next.push({ id: crypto.randomUUID(), dataUrl: await fileToDataUrl(file), name: file.name });
  }
  return next;
}

const GenerateForm = forwardRef(function GenerateForm({
  user,
  models,
  defaultModel,
  keys = {},
  busy,
  onGenerate,
  onNeedLogin,
  onNeedKeys,
}, ref) {
  const [mode, setMode] = useState("text-to-image");
  const [modelName, setModelName] = useState(() => localStorage.getItem("nb_model") || defaultModel || "nano-banana-pro");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [rewrite, setRewrite] = useState(() => localStorage.getItem("nb_rewrite") === "1");
  const [resolution, setResolution] = useState("1K");
  const [aspect, setAspect] = useState("1:1");
  const [aspectOpen, setAspectOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [steps, setSteps] = useState(50);
  const [guidance, setGuidance] = useState(7.5);
  const [seed, setSeed] = useState("");
  const [refs, setRefs] = useState([]);
  const [dragId, setDragId] = useState(null);

  useEffect(() => {
    if (!localStorage.getItem("nb_model") && defaultModel) setModelName(defaultModel);
  }, [defaultModel]);

  useEffect(() => {
    if (!models || Object.keys(models).length === 0) return;
    if (typeof keys.has_bananalab_key !== "boolean") return;
    if (models[modelName] && modelHasKey(models[modelName], keys)) return;
    const ids = Object.keys(models);
    const fallback =
      ids.find((id) => modelHasKey(models[id], keys)) ||
      (models[defaultModel] ? defaultModel : ids[0]);
    if (!fallback || fallback === modelName) return;
    setModelName(fallback);
    localStorage.setItem("nb_model", fallback);
  }, [models, modelName, defaultModel, keys]);

  useEffect(() => {
    if (!aspectOpen && !modelOpen) return undefined;
    const close = () => {
      setAspectOpen(false);
      setModelOpen(false);
    };
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [aspectOpen, modelOpen]);

  useImperativeHandle(ref, () => ({
    applyGeneration(gen, { modelOverride } = {}) {
      setPrompt(gen.prompt || "");
      setNegative(gen.negative_prompt || "");
      setResolution(gen.resolution || "1K");
      setAspect(gen.aspect_ratio || "1:1");
      setSteps(gen.num_inference_steps || 50);
      setGuidance(gen.guidance_scale || 7.5);
      setSeed(gen.seed == null ? "" : String(gen.seed));
      const nextModel = modelOverride || gen.model_name;
      if (nextModel) {
        setModelName(nextModel);
        localStorage.setItem("nb_model", nextModel);
      }
      const urls = gen.reference_images || [];
      setRefs(urls.map((url) => ({ id: crypto.randomUUID(), dataUrl: url, name: "ref" })));
      setMode(urls.length || gen.generation_mode === "image-to-image" ? "image-to-image" : "text-to-image");
      toast("Форма заполнена параметрами генерации");
    },
  }));

  const modelEntry = models[modelName] || {};
  const profile = modelEntry.params_profile || "nano";
  const showStepsGuidance = !["nano", "imagen", "gpt_openrouter"].includes(profile);
  const needsRefs = mode === "image-to-image";
  const aspectMeta = ASPECTS.find(([v]) => v === aspect) || ASPECTS[0];

  const grouped = {};
  Object.entries(models).forEach(([id, m]) => {
    const key = m.group || m.color || "other";
    (grouped[key] ||= []).push([id, m]);
  });
  const modelUnlocked = modelHasKey(modelEntry, keys);

  async function addFiles(files) {
    const extra = await collectImageFiles(files);
    if (!extra.length) return;
    setRefs((prev) => {
      const merged = [...prev, ...extra].slice(0, 4);
      return merged;
    });
    setMode("image-to-image");
  }

  function reorderRefs(fromId, toId) {
    if (!fromId || !toId || fromId === toId) return;
    setRefs((prev) => {
      const next = [...prev];
      const from = next.findIndex((item) => item.id === fromId);
      const to = next.findIndex((item) => item.id === toId);
      if (from < 0 || to < 0) return prev;
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  async function pasteRefs() {
    try {
      if (navigator.clipboard?.read) {
        const items = await navigator.clipboard.read();
        const files = [];
        for (const item of items) {
          const type = item.types.find((t) => t.startsWith("image/"));
          if (!type) continue;
          files.push(new File([await item.getType(type)], "clipboard.png", { type }));
        }
        if (files.length) await addFiles(files);
        else toast("В буфере нет изображения", "error");
      } else {
        toast("Вставка из буфера в этом браузере недоступна", "error");
      }
    } catch (err) {
      toast(err.message || "Не удалось вставить изображение", "error");
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!user) {
      onNeedLogin();
      return;
    }
    if (!modelHasKey(models[modelName], keys)) {
      toast("Добавьте нужный API ключ в настройках", "warning");
      onNeedKeys?.();
      return;
    }
    await onGenerate({
      prompt,
      negative_prompt: negative || null,
      generation_mode: mode,
      model_name: modelName,
      resolution,
      aspect_ratio: aspect,
      guidance_scale: Number(guidance),
      num_inference_steps: Number(steps),
      seed: seed === "" ? null : Number(seed),
      rewrite_prompt: rewrite,
      reference_images: refs.map((r) => r.dataUrl),
    });
  }

  return (
    <div className="card shadow generate-form-card" id="generate-form">
      <div className="card-header">
        <h5 className="mb-0">Генерация изображения</h5>
      </div>
      <div className="card-body">
        <form onSubmit={onSubmit}>
          <div className="mb-3 btn-group w-100">
            <button
              type="button"
              className={`btn ${mode === "text-to-image" ? "btn-primary" : "btn-outline-primary"}`}
              onClick={() => setMode("text-to-image")}
            >
              Text-to-Image
            </button>
            <button
              type="button"
              className={`btn ${mode === "image-to-image" ? "btn-primary" : "btn-outline-primary"}`}
              onClick={() => setMode("image-to-image")}
            >
              Image-to-Image
            </button>
          </div>
          <div className="mb-3">
            <label className="form-label">Модель</label>
            <div className="custom-dropdown model-dropdown">
              <div
                className={`custom-dropdown-selected ${modelOpen ? "active" : ""}`}
                role="button"
                tabIndex={0}
                aria-haspopup="listbox"
                aria-expanded={modelOpen}
                onClick={(e) => {
                  e.stopPropagation();
                  setAspectOpen(false);
                  setModelOpen((open) => !open);
                }}
              >
                <span className={`model-provider-badge model-badge-selected model-badge-${modelEntry.color || "replicate"}`}>
                  {PROVIDER_BADGE[modelEntry.color] || modelEntry.color || ""}
                </span>
                <span className="custom-dropdown-text">{modelEntry.display_name || modelName}</span>
                <span className="custom-dropdown-arrow">▾</span>
              </div>
              <div className={`custom-dropdown-menu model-dropdown-menu ${modelOpen ? "show" : ""}`} role="listbox">
                {GROUP_ORDER.filter((group) => grouped[group]?.length).map((group) => (
                  <div key={group} className="custom-dropdown-group">
                    <div className="custom-dropdown-group-label">{GROUP_LABELS[group] || group}</div>
                    {grouped[group].map(([id, m]) => {
                      const enabled = modelHasKey(m, keys);
                      return (
                        <button
                          type="button"
                          key={id}
                          role="option"
                          className={`custom-dropdown-item model-dropdown-item model-tone-${m.color || "replicate"} ${
                            id === modelName ? "selected" : ""
                          } ${enabled ? "" : "is-disabled"}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (!enabled) {
                              toast("Добавьте нужный API ключ в настройках", "warning");
                              onNeedKeys?.();
                              return;
                            }
                            setModelName(id);
                            localStorage.setItem("nb_model", id);
                            setModelOpen(false);
                          }}
                        >
                          <span className={`model-provider-badge model-badge-${m.color || "replicate"}`}>
                            {PROVIDER_BADGE[m.color] || m.color}
                          </span>
                          <span className="model-dropdown-item-title">{m.display_name}</span>
                          {!enabled && (
                            <span className="model-dropdown-item-lock" title="Нужен API ключ">
                              <i className="fas fa-lock" />
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
            <small className="text-muted d-block mt-1">
              {modelUnlocked ? modelEntry.description : "Для этой модели нужен API ключ"}
            </small>
            <div className="model-provider-legend mt-2">
              {Object.entries(GROUP_LABELS).map(([key, label]) => (
                <span key={key} className={`model-legend-item model-legend-${key}`}>
                  {label}
                </span>
              ))}
            </div>
          </div>
          {needsRefs && (
            <div
              className={`mb-3 reference-drop-zone ${dragId ? "is-reordering" : ""}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
              }}
              onPaste={(e) => {
                const files = [...(e.clipboardData?.files || [])];
                if (files.length) addFiles(files);
              }}
            >
              <p className="mb-2">Перетащите до 4 референсов, выберите файлы или вставьте из буфера. Можно менять местами.</p>
              <div className="d-flex gap-2 flex-wrap">
                <input className="form-control form-control-sm" type="file" accept="image/*" multiple onChange={(e) => addFiles(e.target.files)} />
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={pasteRefs}>
                  Вставить из буфера
                </button>
              </div>
              <div className="d-flex flex-wrap gap-2 mt-3">
                {refs.map((r, idx) => (
                  <div
                    key={r.id}
                    className={`reference-item ${dragId === r.id ? "dragging" : ""}`}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", r.id);
                      setDragId(r.id);
                    }}
                    onDragEnd={() => setDragId(null)}
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      if (e.dataTransfer.files?.length) {
                        addFiles(e.dataTransfer.files);
                        return;
                      }
                      reorderRefs(e.dataTransfer.getData("text/plain") || dragId, r.id);
                      setDragId(null);
                    }}
                  >
                    <img src={r.dataUrl} alt={`Реф ${idx + 1}`} draggable={false} />
                    <span className="reference-label">Реф {idx + 1}</span>
                    <button
                      type="button"
                      className="reference-remove"
                      title="Удалить референс"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={() => setRefs(refs.filter((x) => x.id !== r.id))}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="mb-3">
            <label className="form-label">Описание</label>
            <textarea className="form-control" rows="3" required value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </div>
          <div className="form-check mb-3">
            <input
              className="form-check-input"
              type="checkbox"
              checked={rewrite}
              onChange={(e) => {
                setRewrite(e.target.checked);
                localStorage.setItem("nb_rewrite", e.target.checked ? "1" : "0");
              }}
              id="rewrite"
            />
            <label className="form-label form-check-label" htmlFor="rewrite">
              GPT: авто-переписать при блокировке фильтра
            </label>
          </div>
          <div className="mb-3">
            <label className="form-label">Негативный промпт</label>
            <textarea className="form-control" rows="2" value={negative} onChange={(e) => setNegative(e.target.value)} />
          </div>
          <div className="row mb-3">
            <div className="col-6">
              <label className="form-label">Разрешение</label>
              <select className="form-select" value={resolution} onChange={(e) => setResolution(e.target.value)}>
                <option>1K</option>
                <option>2K</option>
                <option>4K</option>
              </select>
            </div>
            <div className="col-6">
              <label className="form-label">Соотношение</label>
              <div className="custom-dropdown">
                <div
                  className={`custom-dropdown-selected ${aspectOpen ? "active" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setModelOpen(false);
                    setAspectOpen((v) => !v);
                  }}
                >
                  <span className="custom-dropdown-icon">
                    <img src={aspectMeta[2]} alt="" />
                  </span>
                  <span className="custom-dropdown-text">{aspectMeta[1]}</span>
                  <span className="custom-dropdown-arrow">▾</span>
                </div>
                <div className={`custom-dropdown-menu ${aspectOpen ? "show" : ""}`}>
                  {ASPECTS.map(([value, label, icon]) => (
                    <button
                      type="button"
                      key={value}
                      className={`custom-dropdown-item ${value === aspect ? "selected" : ""}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setAspect(value);
                        setAspectOpen(false);
                      }}
                    >
                      <span className="custom-dropdown-item-icon">
                        <img src={icon} alt="" />
                      </span>
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
          {showStepsGuidance && (
            <div className="row mb-3">
              <div className="col-6">
                <label className="form-label">Шаги</label>
                <input className="form-control" type="number" value={steps} onChange={(e) => setSteps(e.target.value)} />
              </div>
              <div className="col-6">
                <label className="form-label">Guidance</label>
                <input className="form-control" type="number" step="0.5" value={guidance} onChange={(e) => setGuidance(e.target.value)} />
              </div>
            </div>
          )}
          <div className="mb-3">
            <label className="form-label">Seed</label>
            <input className="form-control" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="пусто = случайный" />
          </div>
          <button id="sendToGenerate" className="btn btn-primary w-100" disabled={busy}>
            {busy ? "Отправка…" : "Сгенерировать"}
          </button>
        </form>
      </div>
    </div>
  );
});

export default GenerateForm;
