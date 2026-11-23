import { copyText, formatUsd, PROVIDER_BADGE } from "../toast.js";

function inferProvider(item) {
  if (item?.provider) return item.provider;
  const m = String(item?.model_name || "").toLowerCase();
  if (m.startsWith("gpt-") || m.includes("openrouter")) return "openrouter";
  if (m.startsWith("nano-banana") || m.startsWith("gemini-") || m.startsWith("imagen-")) return "bananalab";
  if (m.includes("replicate") || m.startsWith("r8")) return "replicate";
  return null;
}

function modelCostText(item, provider) {
  if (item.provider_cost_usd != null) {
    if (provider === "openrouter") return `${formatUsd(item.provider_cost_usd)} списал OpenRouter`;
    if (provider === "bananalab") return `${formatUsd(item.provider_cost_usd)} списал Moonez`;
    return formatUsd(item.provider_cost_usd);
  }
  if (item.status === "failed") return "нет (генка не прошла)";
  if (item.estimated_cost_usd != null) {
    if (provider === "openrouter") {
      return `~${formatUsd(item.estimated_cost_usd)} оценка по прайсу (ключ sk-or_)`;
    }
    if (provider === "bananalab") {
      return `~${formatUsd(item.estimated_cost_usd)} оценка, пока Moonez не отдал price`;
    }
    return `~${formatUsd(item.estimated_cost_usd)} оценка`;
  }
  return "—";
}

export default function ParamsModal({ item, onClose }) {
  if (!item) return null;
  const provider = inferProvider(item);
  const providerLabel = PROVIDER_BADGE[provider] || provider;
  const done = item.status === "completed";
  return (
    <div className="generation-params-modal" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}>
        <div className="generation-params-modal__head">
          <h5 className="mb-0">Параметры генерации</h5>
          <button type="button" className="generation-params-modal__close" aria-label="Закрыть" onClick={onClose}>
            ×
          </button>
        </div>
        <p>
          <strong>Модель:</strong> {item.model_name}
          {providerLabel ? (
            <span className="badge bg-secondary ms-2">{providerLabel}</span>
          ) : null}
          {item.provider_model ? (
            <span className="small text-muted ms-2">upstream: {item.provider_model}</span>
          ) : null}
        </p>
        <p>
          <strong>ID на сайте:</strong>{" "}
          <button
            type="button"
            className="btn btn-link btn-sm p-0 copy-id"
            onClick={() => copyText(item.id, "ID генерации")}
          >
            #{item.id}
          </button>
        </p>
        {item.provider_job_id && provider === "bananalab" ? (
          <p>
            <strong>Moonez job id:</strong>{" "}
            <button
              type="button"
              className="btn btn-link btn-sm p-0 copy-id"
              title="Сверить в кабинете Moonez"
              onClick={() => copyText(item.provider_job_id, "Moonez job id")}
            >
              {item.provider_job_id}
            </button>
          </p>
        ) : null}
        <p className="mb-1">
          <strong>Стоимость модели:</strong> {modelCostText(item, provider)}
        </p>
        {item.gpt_rewrite_cost_usd != null ? (
          <p className="mb-1">
            <strong>Стоимость GPT{item.rewrite_model ? ` · ${item.rewrite_model}` : ""}:</strong>{" "}
            {formatUsd(item.gpt_rewrite_cost_usd)}
          </p>
        ) : null}
        {(() => {
          const model =
            item.provider_cost_usd != null
              ? Number(item.provider_cost_usd)
              : item.status !== "failed" && item.estimated_cost_usd != null
                ? Number(item.estimated_cost_usd)
                : 0;
          const gpt = Number(item.gpt_rewrite_cost_usd) || 0;
          if (!Number.isFinite(model) && gpt <= 0) return null;
          const total = (Number.isFinite(model) ? model : 0) + gpt;
          const approx = item.provider_cost_usd == null && item.status !== "failed";
          return (
            <p>
              <strong>Итого:</strong> {approx ? "~" : ""}
              {formatUsd(total)}
            </p>
          );
        })()}
        <p>
          <strong>Разрешение / кадр:</strong> {item.resolution || "—"} · {item.aspect_ratio || "—"}
        </p>
        <p>
          <strong>Статус:</strong> {item.status}
          {!done && item.status_detail ? ` · ${item.status_detail}` : ""}
          {!done && item.provider_phase ? ` (${item.provider_phase})` : ""}
        </p>
        {(() => {
          const original = item.original_prompt || item.prompt || "";
          const rewritten = item.rewritten_prompt || "";
          const hasRewrite = Boolean(rewritten && rewritten !== original);
          return (
            <>
              <div className="mb-3">
                <p className="mb-2">
                  <strong>{hasRewrite ? "Исходный промпт:" : "Промпт:"}</strong>
                </p>
                <p
                  className="small mb-0"
                  style={{
                    background: hasRewrite ? "rgba(10, 132, 255, 0.08)" : "rgba(255,255,255,0.04)",
                    padding: "0.75rem",
                    borderRadius: hasRewrite ? 10 : 6,
                  }}
                >
                  {original || "—"}
                </p>
              </div>
              {hasRewrite ? (
                <div className="mb-3">
                  <p className="mb-2">
                    <strong>Переписан GPT{item.rewrite_model ? ` · ${item.rewrite_model}` : ""}:</strong>
                  </p>
                  <p className="small mb-0" style={{ background: "rgba(16, 185, 129, 0.12)", padding: "0.75rem", borderRadius: 6 }}>
                    {rewritten}
                  </p>
                </div>
              ) : null}
            </>
          );
        })()}
        {item.sanitized_prompt && item.sanitized_prompt !== item.prompt && (
          <div className="mb-3">
            <p className="mb-2">
              <strong>После санитизации:</strong>
            </p>
            <p className="small mb-0">{item.sanitized_prompt}</p>
          </div>
        )}
        {item.error_message && (
          <div className="alert alert-danger small mb-0">{item.error_message}</div>
        )}
      </div>
    </div>
  );
}
