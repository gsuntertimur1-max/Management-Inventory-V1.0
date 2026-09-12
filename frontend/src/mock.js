// Kategori & util format untuk Bulog Gudang Sunter Timur I & II

export const DEFAULT_CATEGORIES = [
  { name: 'Beras', color: '#f59e0b' },
  { name: 'Minyak', color: '#eab308' },
  { name: 'Gula', color: '#ec4899' },
  { name: 'Tepung', color: '#a855f7' },
  { name: 'Sarden', color: '#3b82f6' },
  { name: 'Teh', color: '#22c55e' },
  { name: 'Margarin', color: '#f97316' },
  { name: 'Kecap', color: '#8b5cf6' },
  { name: 'Kopi', color: '#b45309' },
  { name: 'Susu', color: '#22d3ee' },
];

// Alias lama dipertahankan agar komponen yang belum memakai master kategori tetap aman.
export const CATEGORIES = DEFAULT_CATEGORIES;
export const catColor = (name, categories = DEFAULT_CATEGORIES) => (categories.find((c) => c.name === name)?.color || '#64748b');

export const formatRp = (n) => 'Rp ' + Math.round(n || 0).toLocaleString('id-ID');
export const formatRpShort = (n) => {
  if (n >= 1e12) return 'Rp ' + (n / 1e12).toFixed(1) + ' T';
  if (n >= 1e9) return 'Rp ' + (n / 1e9).toFixed(1) + ' M';
  if (n >= 1e6) return 'Rp ' + (n / 1e6).toFixed(1) + ' Jt';
  return 'Rp ' + Math.round(n || 0).toLocaleString('id-ID');
};
export const formatNum = (n) => (n || 0).toLocaleString('id-ID');
export const formatDate = (iso) => {
  const d = new Date(iso);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}, ${String(d.getHours()).padStart(2, '0')}.${String(d.getMinutes()).padStart(2, '0')}`;
};
