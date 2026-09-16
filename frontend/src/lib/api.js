import axios from 'axios';

const configuredBackend = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');

const api = axios.create({
  // Railway production serves frontend and API from the same domain.
  // REACT_APP_BACKEND_URL remains optional for local development.
  baseURL: `${configuredBackend}/api`,
  withCredentials: true,
});

const MUTATING_METHODS = new Set(['post', 'put', 'patch', 'delete']);
const VALID_STACK_CODE = /^(?:1[7-9]|2[0-4]|MP1)\/[ABC]\d{2}$/i;

const parsePayload = (value) => {
  if (!value) return {};
  if (typeof value === 'string') {
    try { return JSON.parse(value); } catch (_) { return {}; }
  }
  return value;
};

const hashText = (value) => {
  let hash = 2166136261;
  const text = String(value || '');
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
};

const newRequestId = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
};

const idempotencyStorageKey = (config) => {
  const method = String(config.method || 'get').toLowerCase();
  const payload = typeof config.data === 'string' ? config.data : JSON.stringify(config.data ?? null);
  return `bulog_idem_${hashText(`${method}|${config.url || ''}|${payload}`)}`;
};

const clearIdempotencyKey = (config) => {
  const key = config?.__bulogIdempotencyStorageKey;
  if (key) sessionStorage.removeItem(key);
};

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('bulog_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;

  const method = String(config.method || 'get').toLowerCase();
  const path = String(config.url || '').split('?')[0];

  // Penerimaan stok Baik harus menunjuk tumpukan fisik yang spesifik.
  // Jangan lagi membiarkan nilai generik seperti "GBB 18" lolos sebagai fallback.
  if (method === 'post' && path === '/receipts') {
    const payload = parsePayload(config.data);
    const invalidItem = (payload.items || []).find((item) => {
      const goodQty = Number(item.goodQty ?? (String(payload.kondisi || 'BAIK').toUpperCase() === 'BAIK' ? item.qty : 0) ?? 0);
      return goodQty > 0 && !VALID_STACK_CODE.test(String(item.stackCode || '').trim());
    });
    if (invalidItem) {
      const error = new Error('Tumpukan penerimaan wajib dipilih untuk setiap stok Baik');
      error.response = { status: 400, data: { detail: 'Tumpukan penerimaan wajib dipilih untuk setiap stok Baik (contoh 18/A01).' } };
      return Promise.reject(error);
    }
  }

  if (MUTATING_METHODS.has(method)) {
    const storageKey = idempotencyStorageKey(config);
    let requestId = sessionStorage.getItem(storageKey);
    if (!requestId) {
      requestId = newRequestId();
      sessionStorage.setItem(storageKey, requestId);
    }
    config.headers['X-Idempotency-Key'] = requestId;
    config.__bulogIdempotencyStorageKey = storageKey;
  }

  return config;
});

api.interceptors.response.use(
  (response) => {
    clearIdempotencyKey(response.config);
    return response;
  },
  (error) => {
    // Bila server sudah menjawab, request aman untuk diberi ID baru pada submit berikutnya.
    // Untuk network timeout/disconnect, kunci dipertahankan sehingga retry memakai ID yang sama.
    if (error?.response) {
      const detail = String(error.response?.data?.detail || '').toLowerCase();
      const stillProcessing = error.response.status === 409 && detail.includes('sedang diproses');
      if (!stillProcessing) clearIdempotencyKey(error.config);
    }
    return Promise.reject(error);
  },
);

export const setToken = (token) => {
  if (token) localStorage.setItem('bulog_token', token);
  else localStorage.removeItem('bulog_token');
};

export const downloadApiFile = async (path, fallbackName = 'download.xlsx') => {
  const response = await api.get(path, { responseType: 'blob' });
  const disposition = response.headers?.['content-disposition'] || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match?.[1] || fallbackName;

  const url = URL.createObjectURL(response.data);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  return filename;
};

export const printApiFile = async (path) => {
  const response = await api.get(path, { responseType: 'blob' });
  const url = URL.createObjectURL(response.data);
  const frame = document.createElement('iframe');
  frame.style.position = 'fixed'; frame.style.right = '0'; frame.style.bottom = '0'; frame.style.width = '0'; frame.style.height = '0'; frame.style.border = '0';
  frame.src = url;
  document.body.appendChild(frame);
  frame.onload = () => { frame.contentWindow?.focus(); frame.contentWindow?.print(); setTimeout(() => { frame.remove(); URL.revokeObjectURL(url); }, 1200); };
};

export const apiError = (e) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join(' ');
  return e?.message || 'Terjadi kesalahan';
};

export default api;
