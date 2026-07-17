async function request(path, options = {}) {
  const opts = {
    credentials: "include",
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.headers || {}),
    },
  };
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail || res.statusText);
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  me: () => request("/api/auth/me"),
  login: (body) => request("/api/auth/login", { method: "POST", body }),
  signup: (body) => request("/api/auth/signup", { method: "POST", body }),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  demoInfo: () => request("/api/demo/info"),
  startDemo: () => request("/api/demo/start", { method: "POST" }),
  demoContext: () => request("/api/demo/context"),
  resetDemo: () => request("/api/demo/reset", { method: "POST" }),
  dashboard: () => request("/api/dashboard"),
  billing: () => request("/api/billing"),
  upgrade: () => request("/api/billing/upgrade", { method: "POST" }),
  projects: () => request("/api/projects"),
  project: (id) => request(`/api/projects/${id}`),
  createProject: (body) => request("/api/projects", { method: "POST", body }),
  uploadDrawing: (projectId, file, versionLabel) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("version_label", versionLabel || "Rev A");
    return request(`/api/projects/${projectId}/drawings`, { method: "POST", body: fd });
  },
  startAudit: (projectId, drawingId) => {
    const q = drawingId ? `?drawing_id=${encodeURIComponent(drawingId)}` : "";
    return request(`/api/projects/${projectId}/audits${q}`, { method: "POST" });
  },
  audits: () => request("/api/audits"),
  audit: (id) => request(`/api/audits/${id}`),
  triage: (auditId, findingId, body) =>
    request(`/api/audits/${auditId}/findings/${findingId}`, { method: "PATCH", body }),
};
