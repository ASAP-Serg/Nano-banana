import { useEffect, useState } from "react";
import { api } from "../api.js";
import { copyText, formatUsd, isSafeMediaUrl, shortJobId, toast } from "../toast.js";
import { IconToForm } from "../icons.jsx";
import Lightbox from "./Lightbox.jsx";
import Modal from "./Modal.jsx";

function formatAgo(iso) {
  if (!iso) return "никогда";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "никогда";
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return "сегодня";
  if (days === 1) return "вчера";
  if (days < 30) return `${days} дн.`;
  const months = Math.max(1, Math.floor(days / 30));
  return `${months} мес.`;
}

export default function AdminPanel({ onClose, onInsertToForm }) {
  const [users, setUsers] = useState([]);
  const [gens, setGens] = useState([]);
  const [overview, setOverview] = useState(null);
  const [filters, setFilters] = useState({ users: [], models: [], providers: [], statuses: [] });
  const [query, setQuery] = useState({
    search: "",
    status: "",
    model: "",
    provider: "",
    user_id: "",
    error_only: false,
  });
  const [page, setPage] = useState(0);
  const [lightbox, setLightbox] = useState(null);
  const [pwModal, setPwModal] = useState(null);
  const [pwValue, setPwValue] = useState("");
  const [idleOnly, setIdleOnly] = useState(false);
  const pageSize = 24;

  function askPassword(title) {
    return new Promise((resolve) => {
      setPwValue("");
      setPwModal({ title, resolve });
    });
  }

  async function runUserAction(title, fn) {
    const password = await askPassword(title);
    if (!password) return;
    try {
      const result = await fn(password);
      toast(result?.message || "Готово");
      load();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function load(nextIdleOnly = idleOnly) {
    try {
      const [u, o, f] = await Promise.all([
        api.adminUsers(nextIdleOnly ? { idle_only: true } : {}),
        api.adminOverview(),
        api.adminFilters(),
      ]);
      setUsers(u.users || []);
      setOverview(o);
      setFilters(f);
    } catch (e) {
      toast(e.message, "error");
    }
  }

  async function loadGens(nextPage = page, nextQuery = query) {
    try {
      const params = {
        limit: pageSize,
        offset: nextPage * pageSize,
        search: nextQuery.search,
        status: nextQuery.status,
        model: nextQuery.model,
        provider: nextQuery.provider,
        user_id: nextQuery.user_id,
        error_only: nextQuery.error_only || undefined,
      };
      const d = await api.adminGenerations(params);
      setGens(d.generations || []);
    } catch (e) {
      toast(e.message, "error");
    }
  }

  useEffect(() => {
    load();
    loadGens(0, query);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="row g-4 justify-content-center mt-2">
      <div className="col-12">
        <div className="card shadow admin-shell">
          <div className="card-header d-flex justify-content-between">
            <h5 className="mb-0">Админ-панель</h5>
            <button className="btn btn-sm btn-outline-light" onClick={onClose}>
              Закрыть
            </button>
          </div>
          <div className="card-body">
            {overview && (
              <div className="row g-3 mb-3">
                <div className="col-md-3">
                  <div className="card p-3">Пользователи: {overview.users_total}</div>
                </div>
                <div className="col-md-3">
                  <div className="card p-3">Генерации: {overview.generations_total}</div>
                </div>
                <div className="col-md-3">
                  <div className="card p-3">Успешно: {overview.completed_total}</div>
                </div>
                <div className="col-md-3">
                  <div className="card p-3">Ошибки: {overview.failed_total}</div>
                </div>
                <div className="col-md-3">
                  <div className="card p-3">Расход ~ ${overview.spend_total_usd}</div>
                </div>
                <div className="col-md-3">
                  <div className="card p-3">
                    Без генераций {overview.idle_days || 60}+ дн.: {overview.idle_users ?? 0}
                  </div>
                </div>
              </div>
            )}
            <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
              <h6 className="mb-0">Пользователи</h6>
              <div className="form-check">
                <input
                  className="form-check-input"
                  type="checkbox"
                  id="adminIdleOnly"
                  checked={idleOnly}
                  onChange={(e) => {
                    const next = e.target.checked;
                    setIdleOnly(next);
                    load(next);
                  }}
                />
                <label className="form-check-label" htmlFor="adminIdleOnly">
                  только без генераций 2+ мес.
                </label>
              </div>
            </div>
            <p className="form-text text-muted mt-0 mb-2">
              Мёртвый — не админ и нет генераций 60+ дней (или аккаунт старше 60 дней без единой генерации). Удаление только вручную.
            </p>
            <div className="table-responsive">
            <table className="table table-sm">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Username</th>
                  <th>Email</th>
                  <th>Admin</th>
                  <th>Статус</th>
                  <th>Генерации</th>
                  <th>Последняя генерация</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {users.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-muted">
                      {idleOnly ? "Нет аккаунтов без генераций 2+ месяцев." : "Нет пользователей."}
                    </td>
                  </tr>
                )}
                {users.map((u) => (
                  <tr key={u.id} className={u.is_idle ? "table-warning" : undefined}>
                    <td>{u.id}</td>
                    <td>{u.username}</td>
                    <td>{u.email}</td>
                    <td>{u.is_admin ? "да" : "нет"}</td>
                    <td>{u.is_active === false ? "выкл" : "активен"}</td>
                    <td>{u.generation_count ?? 0}</td>
                    <td>
                      <span title={u.last_generated_at || ""}>{formatAgo(u.last_generated_at)}</span>
                      {u.is_idle && (
                        <span className="badge text-bg-warning ms-2">2+ мес.</span>
                      )}
                    </td>
                    <td>
                      <div className="d-flex flex-wrap gap-1">
                        {u.is_admin ? (
                          <button
                            className="btn btn-sm btn-outline-warning"
                            onClick={() => runUserAction("Снять права админа", (password) => api.adminRevoke(u.id, password))}
                          >
                            Снять
                          </button>
                        ) : (
                          <button
                            className="btn btn-sm btn-outline-primary"
                            onClick={() => runUserAction("Назначить админом", (password) => api.adminGrant(u.id, password))}
                          >
                            Админ
                          </button>
                        )}
                        {u.is_active === false ? (
                          <button
                            className="btn btn-sm btn-outline-success"
                            onClick={() => runUserAction("Включить пользователя", (password) => api.adminActivate(u.id, password))}
                          >
                            Вкл
                          </button>
                        ) : (
                          <button
                            className="btn btn-sm btn-outline-secondary"
                            onClick={() => runUserAction("Выключить пользователя", (password) => api.adminDeactivate(u.id, password))}
                          >
                            Выкл
                          </button>
                        )}
                        <button
                          className="btn btn-sm btn-outline-danger"
                          onClick={() => {
                            if (!window.confirm(`Удалить ${u.username}? Генерации и файлы тоже будут удалены.`)) return;
                            runUserAction("Удалить пользователя", (password) => api.adminDeleteUser(u.id, password));
                          }}
                        >
                          Удалить
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <h6 className="mt-4">Генерации</h6>
            <div className="row g-2 mb-3">
              <div className="col-md-3">
                <input
                  className="form-control"
                  placeholder="Поиск по промпту"
                  value={query.search}
                  onChange={(e) => setQuery({ ...query, search: e.target.value })}
                />
              </div>
              <div className="col-md-2">
                <select className="form-select" value={query.status} onChange={(e) => setQuery({ ...query, status: e.target.value })}>
                  <option value="">Статус</option>
                  {(filters.statuses || []).map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div className="col-md-2">
                <select className="form-select" value={query.model} onChange={(e) => setQuery({ ...query, model: e.target.value })}>
                  <option value="">Модель</option>
                  {(filters.models || []).map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div className="col-md-2">
                <select className="form-select" value={query.provider} onChange={(e) => setQuery({ ...query, provider: e.target.value })}>
                  <option value="">Провайдер</option>
                  {(filters.providers || []).map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div className="col-md-2">
                <select className="form-select" value={query.user_id} onChange={(e) => setQuery({ ...query, user_id: e.target.value })}>
                  <option value="">Пользователь</option>
                  {(filters.users || []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-md-1 d-flex align-items-center">
                <div className="form-check">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    checked={query.error_only}
                    onChange={(e) => setQuery({ ...query, error_only: e.target.checked })}
                    id="adminErrorOnly"
                  />
                  <label className="form-check-label" htmlFor="adminErrorOnly">
                    ошибки
                  </label>
                </div>
              </div>
              <div className="col-12">
                <button
                  className="btn btn-sm btn-primary me-2"
                  onClick={() => {
                    setPage(0);
                    loadGens(0, query);
                  }}
                >
                  Применить
                </button>
                <button
                  className="btn btn-sm btn-outline-secondary"
                  disabled={page === 0}
                  onClick={() => {
                    const next = Math.max(0, page - 1);
                    setPage(next);
                    loadGens(next, query);
                  }}
                >
                  Назад
                </button>
                <button
                  className="btn btn-sm btn-outline-secondary ms-1"
                  onClick={() => {
                    const next = page + 1;
                    setPage(next);
                    loadGens(next, query);
                  }}
                >
                  Дальше
                </button>
              </div>
            </div>
            <div className="media-grid">
              {gens.map((g) => (
                <div className="gallery-card-wrap" key={g.id}>
                  <div className="card admin-gen-card">
                    <div className="media-thumb">
                      {g.result_url && isSafeMediaUrl(g.result_url) ? (
                        <img
                          src={g.result_url}
                          alt=""
                          onClick={() => {
                            const items = gens.filter((item) => item.result_url && isSafeMediaUrl(item.result_url));
                            const idx = items.findIndex((item) => item.id === g.id);
                            if (idx >= 0) setLightbox(idx);
                          }}
                        />
                      ) : (
                        <div className="media-thumb-empty">{g.status || "нет фото"}</div>
                      )}
                    </div>
                    <div className="card-body small">
                      <div>
                        #{g.id} · {g.username} · {g.status} · {g.model_name}
                      </div>
                      <div className="admin-gen-meta text-muted">
                        {g.provider_cost_usd != null
                          ? `${formatUsd(g.provider_cost_usd)} Moonez`
                          : g.estimated_cost_usd != null
                            ? `~${formatUsd(g.estimated_cost_usd)} оценка`
                            : ""}
                        {g.provider_job_id ? (
                          <>
                            {" · "}
                            <button
                              type="button"
                              className="btn btn-link btn-sm p-0 copy-id"
                              title="Скопировать id задачи Moonez"
                              onClick={() => copyText(g.provider_job_id, "Moonez job id")}
                            >
                              {shortJobId(g.provider_job_id)}
                            </button>
                          </>
                        ) : null}
                      </div>
                      <div className="text-muted">{g.prompt}</div>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-primary mt-2 d-inline-flex align-items-center gap-2"
                        onClick={() => onInsertToForm(g.id)}
                      >
                        <IconToForm />
                        В форму
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {lightbox != null && (
        <Lightbox
          items={gens.filter((item) => item.result_url && isSafeMediaUrl(item.result_url))}
          index={lightbox}
          onClose={() => setLightbox(null)}
          onIndex={setLightbox}
        />
      )}
      {pwModal && (
        <Modal
          title={pwModal.title}
          onClose={() => {
            pwModal.resolve(null);
            setPwModal(null);
          }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              pwModal.resolve(pwValue);
              setPwModal(null);
              setPwValue("");
            }}
          >
            <p className="small text-muted">Подтвердите действие своим паролем.</p>
            <input
              className="form-control mb-3"
              type="password"
              autoComplete="current-password"
              minLength={10}
              value={pwValue}
              onChange={(e) => setPwValue(e.target.value)}
              autoFocus
              required
            />
            <button className="btn btn-primary w-100">Подтвердить</button>
          </form>
        </Modal>
      )}
    </div>
  );
}
