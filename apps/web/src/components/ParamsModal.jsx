import { PROVIDER_BADGE } from "../toast.js";

export default function ParamsModal({ item, onClose }) {
  if (!item) return null;
  const extra = item;
  return (
    <div className="generation-params-modal" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}>
        <div className="d-flex justify-content-between align-items-start mb-3">
          <h5 className="mb-0">Параметры генерации</h5>
          <button type="button" className="btn-close" onClick={onClose} />
        </div>
        <p>
          <strong>Модель:</strong> {item.model_name}
          {item.provider ? (
            <span className="badge bg-secondary ms-2">{PROVIDER_BADGE[item.provider] || item.provider}</span>
          ) : null}
        </p>
        <p>
          <strong>Разрешение / кадр:</strong> {item.resolution || "—"} · {item.aspect_ratio || "—"}
        </p>
        <p>
          <strong>Статус:</strong> {item.status}
        </p>
        {item.original_prompt && (
          <div className="mb-3">
            <p className="mb-2">
              <strong>Исходный промпт:</strong>
            </p>
            <p className="small mb-0" style={{ background: "rgba(102, 126, 234, 0.08)", padding: "0.75rem", borderRadius: 6 }}>
              {item.original_prompt}
            </p>
          </div>
        )}
        <div className="mb-3">
          <p className="mb-2">
            <strong>Промпт:</strong>
          </p>
          <p className="small mb-0" style={{ background: "rgba(255,255,255,0.04)", padding: "0.75rem", borderRadius: 6 }}>
            {item.prompt}
          </p>
        </div>
        {item.rewritten_prompt && (
          <div className="mb-3">
            <p className="mb-2">
              <strong>Переписан GPT{item.rewrite_model ? ` · ${item.rewrite_model}` : ""}:</strong>
            </p>
            <p className="small mb-0" style={{ background: "rgba(16, 185, 129, 0.12)", padding: "0.75rem", borderRadius: 6 }}>
              {item.rewritten_prompt}
            </p>
          </div>
        )}
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
