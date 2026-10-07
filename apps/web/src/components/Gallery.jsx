import { copyText, downloadImage, formatUsd, isSafeMediaUrl, PROVIDER_BADGE, shortJobId, toast } from "../toast.js";
import { IconButton, IconDownload, IconInfo, IconRefresh, IconToForm, IconTrash } from "../icons.jsx";

function statusLabel(item) {
  if (item.status === "pending" || item.status === "running") return "в очереди / идёт";
  if (item.status === "paused") return "пауза";
  return item.status;
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
                  <p className="small mb-1 prompt-text">{item.prompt}</p>
                  <div className="small text-muted">
                    #{item.id} · {item.model_name} · {statusLabel(item)}
                    {item.provider ? ` · ${PROVIDER_BADGE[item.provider] || item.provider}` : ""}
                  </div>
                  {item.provider_cost_usd != null ? (
                    <div className="small text-muted">{formatUsd(item.provider_cost_usd)} Moonez</div>
                  ) : item.status !== "failed" && item.estimated_cost_usd != null ? (
                    <div className="small text-muted">~{formatUsd(item.estimated_cost_usd)} оценка</div>
                  ) : null}
                  {item.provider_job_id ? (
                    <button
                      type="button"
                      className="btn btn-link btn-sm p-0 copy-id"
                      title="Скопировать id задачи Moonez"
                      onClick={() => copyText(item.provider_job_id, "Moonez job id")}
                    >
                      Moonez: {shortJobId(item.provider_job_id)}
                    </button>
                  ) : null}
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
                      onClick={() => onReuse(item.id)}
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
