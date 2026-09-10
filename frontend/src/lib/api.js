import axios from 'axios';

const configuredBackend = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');

const api = axios.create({
  // Production uses the same Vercel domain. REACT_APP_BACKEND_URL remains
  // optional for development against a separately hosted backend.
  baseURL: `${configuredBackend}/api`,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('bulog_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

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

export const apiError = (e) => {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join(' ');
  return e?.message || 'Terjadi kesalahan';
};

export default api;
