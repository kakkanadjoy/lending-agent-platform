// // Thin client over the FastAPI backend. The dev server proxies /api -> :8000,
// // so these paths stay relative. Each function maps to one endpoint the desk
// // needs; the components never build URLs themselves.

// async function request(path, options) {
//   const res = await fetch(`/api${path}`, {
//     headers: { "Content-Type": "application/json" },
//     ...options,
//   });
//   if (!res.ok) {
//     const detail = await res.text();
//     throw new Error(`${res.status}: ${detail}`);
//   }
//   return res.json();
// }

// export function fetchQueue(limit = 20) {
//   return request(`/queue?limit=${limit}`);
// }

// export function startRenewal(loanId, threadId) {
//   return request("/renewals/start", {
//     method: "POST",
//     body: JSON.stringify({ loan_id: loanId, thread_id: threadId }),
//   });
// }

// export function resumeRenewal(threadId, decision) {
//   return request("/renewals/resume", {
//     method: "POST",
//     body: JSON.stringify({ thread_id: threadId, decision }),
//   });
// }

// Thin client over the FastAPI backend. The dev server proxies /api -> :8000,
// so these paths stay relative. Each function maps to one endpoint the desk
// needs; the components never build URLs themselves.

// async function request(path, options) {
//   const res = await fetch(`/api${path}`, {
//     headers: { "Content-Type": "application/json" },
//     ...options,
//   });
//   if (!res.ok) {
//     const detail = await res.text();
//     throw new Error(`${res.status}: ${detail}`);
//   }
//   return res.json();
// }


const API_BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options) {
  const prefix = API_BASE ? "" : "/api";
  const res = await fetch(`${API_BASE}${prefix}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export function fetchQueue(limit = 50) {
  return request(`/queue?limit=${limit}`);
}

export function fetchEvents(limit = 50) {
  return request(`/events?limit=${limit}`);
}

export function startRenewal(loanId, threadId) {
  return request("/renewals/start", {
    method: "POST",
    body: JSON.stringify({ loan_id: loanId, thread_id: threadId }),
  });
}

export function resumeRenewal(threadId, decision) {
  return request("/renewals/resume", {
    method: "POST",
    body: JSON.stringify({ thread_id: threadId, decision }),
  });
}

export function uploadDocument(file) {
  const form = new FormData();
  form.append("file", file);
  const url = API_BASE ? `${API_BASE}/upload` : "/api/upload";
  return fetch(url, { method: "POST", body: form })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
}

export function runTickler() {
  return request("/demo/tickler", { method: "POST" });
}

export function resetPortfolio() {
  return request("/demo/reset", { method: "POST" });
}
