const API = "/api/v1";

/** Legacy: clear XSS-stealable tokens from older builds. */
export function clearLegacyToken() {
  try {
    localStorage.removeItem("nb_token");
    localStorage.removeItem("nb_refresh");
  } catch {
    /* ignore */
  }
}

async function request(path, { method = "GET", body, auth = true, headers = {} } = {}) {
  const opts = {
    method,
    headers: { ...headers },
    credentials: "include",
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API}${path}`, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? JSON.stringify(detail)
          : res.statusText;
    const err = new Error(message || "Ошибка запроса");
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

export const api = {
  login: (username_or_email, password, totp_code) =>
    request("/auth/login", {
      method: "POST",
      body: totp_code
        ? { username_or_email, password, totp_code }
        : { username_or_email, password },
      auth: false,
    }),
  register: (username, email, password) =>
    request("/auth/register", { method: "POST", body: { username, email, password }, auth: false }),
  logout: () => request("/auth/logout", { method: "POST", auth: false }),
  me: () => request("/auth/me"),
  totpBegin: () => request("/auth/totp/begin", { method: "POST" }),
  totpConfirm: (code) => request("/auth/totp/confirm", { method: "POST", body: { code } }),
  models: () => request("/images/models"),
  generate: (payload) => request("/images/generate", { method: "POST", body: payload }),
  list: (limit = 50, offset = 0) => request(`/images/list?limit=${limit}&offset=${offset}`),
  generation: (id) => request(`/images/${id}`),
  deleteGeneration: (id) => request(`/images/${id}`, { method: "DELETE" }),
  serviceStatus: (withAuth = true) => request("/images/service-status", { auth: withAuth }),
  providerStatus: (modelName) =>
    request(`/images/provider-status${modelName ? `?model_name=${encodeURIComponent(modelName)}` : ""}`),
  getKeys: () => request("/users/api-key"),
  setKey: (api_key, provider) => request("/users/api-key", { method: "PUT", body: { api_key, provider } }),
  deleteKeys: () => request("/users/api-key", { method: "DELETE" }),
  adminUsers: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") q.set(k, v);
    });
    const qs = q.toString();
    return request(`/admin/users${qs ? `?${qs}` : ""}`);
  },
  adminFilters: () => request("/admin/filters"),
  adminOverview: (period_days = 30) => request(`/admin/overview?period_days=${period_days}`),
  adminGenerations: (params = {}) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") q.set(k, v);
    });
    return request(`/admin/generations?${q.toString()}`);
  },
  adminGrant: (id, password) =>
    request(`/admin/users/${id}/grant-admin`, { method: "POST", body: { password } }),
  adminRevoke: (id, password) =>
    request(`/admin/users/${id}/revoke-admin`, { method: "POST", body: { password } }),
  adminDeactivate: (id, password) =>
    request(`/admin/users/${id}/deactivate`, { method: "POST", body: { password } }),
  adminActivate: (id, password) =>
    request(`/admin/users/${id}/activate`, { method: "POST", body: { password } }),
  adminDeleteUser: (id, password) =>
    request(`/admin/users/${id}`, { method: "DELETE", body: { password } }),
  adminGeneration: (id) => request(`/admin/generations/${id}`),
};
