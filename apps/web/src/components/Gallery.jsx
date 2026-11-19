import {
  downloadImage,
  formatDurationSeconds,
  formatUsd,
  isSafeMediaUrl,
  toast,
} from "../toast.js";
import { IconButton, IconDownload, IconInfo, IconRefresh, IconToForm, IconTrash } from "../icons.jsx";

function cardStatus(item) {
  if (item.status === "failed") return "ошибка";
  if (item.status === "paused") return "пауза";
  if (item.status === "running") return "генерация";
  if (item.status === "pending") return "очередь";
  return null;
}

function retryWord(n) {
  if (n === 1) return "ретрай";
  if (n >= 2 && n <= 4) return "ретрая";
  return "ретраев";
}

function shortModelName(name) {
  const raw = String(name || "").trim();
  if (!raw) return "—";
  return raw.replace(/^gemini-/i, "").replace(/^nano-banana-/i, "nb-");
}

export default function Gallery({
  user,
  gallery,
  galleryMeta,
  onRefresh,
  onDelete,
  onOpen,
  onInfo,
  onReuse,
  onRetry,
}) {
  return (
    <div className="card shadow">
      <div className="card-header d-flex justify-content-between align-items-start">
        <div>
          <h5 className="mb-0">Мои работы</h5>
          {galleryMeta && (
            <small className="text-muted" id="galleryStats">
              {galleryMeta.shown} из {galleryMeta.total} · хранятся {galleryMeta.storage_info?.retention_days || 7} дней
            </small>
          )}
        </div>
        <IconButton className="btn btn-sm btn-light btn-icon-only" title="Обновить" onClick={onRefresh}>
          <IconRefresh />
        </IconButton>
      </div>
      <div className="card-body">
        <div id="imageGrid" className="media-grid">
          {gallery.map((item, idx) => (
            <div className="gallery-card-wrap" key={item.id}>
              <div className="card">
                <div className="media-thumb">
                  {item.mosaic && (
                    <img className="mosaic-badge" src="/icons/mosaica.svg" alt="Мозаика" title="Мозаика" />
                  )}
                  {item.result_url && isSafeMediaUrl(item.result_url) ? (
                    <img
                      src={item.result_url}
                      className="generation-image"
                      alt=""
                      onClick={() => onOpen(idx)}
                    />
                  ) : (
                    <div className="media-thumb-empty">
                      {item.status === "pending" || item.status === "running" ? (
                        <div className="spinner-border" role="status" />
                      ) : null}
                      <div className="mt-2">{statusLabel(item)}</div>
                    </div>
                  )}
                </div>
                <div className="card-body">
                  <p className="small mb-1 prompt-text">
                    {item.mosaic
                      ? {
                          combo: "Мозаика · Transfer Combo",
                          synthetic: "Мозаика · Synthetic",
                          synthetic_combo: "Мозаика · Synthetic Combo",
                        }[item.mosaic_kind] || "Мозаика · Transfer"
                      : item.prompt}
                  </p>
                  <div className="gallery-meta">
                    <div className="gallery-meta__row gallery-meta__stats">
                      <span className="gallery-meta__model" title={item.model_name || ""}>
                        {shortModelName(item.model_name)}
                      </span>
                      {item.provider_cost_usd != null ? (
                        <span className="gallery-meta__price">{formatUsd(item.provider_cost_usd)}</span>
                      ) : item.status !== "failed" && item.estimated_cost_usd != null ? (
                        <span className="gallery-meta__price gallery-meta__price--est">
                          ~{formatUsd(item.estimated_cost_usd)}
                        </span>
                      ) : null}
                      {item.site_ready_seconds != null ? (
                        <span
                          className="gallery-meta__time"
                          title="До появления картинки на сайте (очередь + генерация + ретраи)"
                        >
                          {formatDurationSeconds(item.site_ready_seconds)}
                        </span>
                      ) : null}
                      {Number(item.retry_count) > 0 ? (
                        <span className="gallery-meta__retries">
                          {item.retry_count} {retryWord(Number(item.retry_count))}
                        </span>
                      ) : null}
                      {cardStatus(item) ? (
                        <span className={`gallery-meta__status gallery-meta__status--${item.status}`}>
                          {cardStatus(item)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  {item.rewritten_prompt && <div className="small text-success mt-1">Промпт переписан GPT</div>}
                  {item.error_message && <div className="small text-danger mt-1">{item.error_message}</div>}
                  <div className="d-flex flex-wrap gap-1 mt-2">
                    {item.result_url && isSafeMediaUrl(item.result_url) && (
                      <IconButton
                        className="btn btn-icon-only btn-download btn-sm"
                        title="Скачать"
                        onClick={() => downloadImage(item.result_url, item.prompt)}
                      >
                        <IconDownload />
                      </IconButton>
                    )}
                    <IconButton
                      className="btn btn-icon-only btn-edit btn-sm"
                      title="Инфо"
                      onClick={() => onInfo(item)}
                    >
                      <IconInfo />
                    </IconButton>
                    <IconButton
                      className="btn btn-icon-only btn-edit btn-sm"
                      title="В форму"
                      onClick={() => onReuse(item)}
                    >
                      <IconToForm />
                    </IconButton>
                    {item.status === "failed" && item.fallback_model && (
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-warning"
                        onClick={() => onRetry(item)}
                      >
                        Retry {item.fallback_model}
                      </button>
                    )}
                    <IconButton
                      className="btn btn-icon-only btn-delete btn-sm"
                      title="Удалить"
                      onClick={async () => {
                        try {
                          await onDelete(item.id);
                        } catch (err) {
                          toast(err.message, "error");
                        }
                      }}
                    >
                      <IconTrash />
                    </IconButton>
                  </div>
                </div>
              </div>
            </div>
          ))}
          {user && gallery.length === 0 && <p className="text-muted media-grid-empty">Пока нет генераций.</p>}
          {!user && <p className="text-muted media-grid-empty">Войдите, чтобы видеть галерею.</p>}
        </div>
      </div>
    </div>
  );
}
