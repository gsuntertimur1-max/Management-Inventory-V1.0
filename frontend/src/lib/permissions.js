// Four-role warehouse access model.
// Stored legacy values remain supported so old accounts can be migrated safely.
export const ROLE_LABELS = {
  Administrator: 'Superadmin',
  Superadmin: 'Superadmin',
  'Kepala Gudang': 'Kepala Gudang',
  Supervisor: 'Admin Operasional',
  Admin: 'Admin Operasional',
  'Admin Operasional': 'Admin Operasional',
  Operator: 'Admin Operasional',
  QC: 'Admin Operasional',
  Mandor: 'Admin Operasional',
  Pemantau: 'Viewer',
  Viewer: 'Viewer',
};

export const ROLE_COLORS = {
  Administrator: '#ef4444',
  Superadmin: '#ef4444',
  'Kepala Gudang': '#f59e0b',
  Supervisor: '#3b82f6',
  Admin: '#3b82f6',
  'Admin Operasional': '#3b82f6',
  Operator: '#3b82f6',
  QC: '#3b82f6',
  Mandor: '#3b82f6',
  Pemantau: '#8b93a1',
  Viewer: '#8b93a1',
};

export const FOUR_ROLES = ['Administrator', 'Kepala Gudang', 'Supervisor', 'Pemantau'];

export const canonicalRole = (role) => ({
  Superadmin: 'Administrator',
  Admin: 'Supervisor',
  'Admin Operasional': 'Supervisor',
  Operator: 'Supervisor',
  QC: 'Supervisor',
  Mandor: 'Supervisor',
  Viewer: 'Pemantau',
}[role] || role || 'Pemantau');

const ROLE_PERMISSIONS = {
  Administrator: new Set(['masterWrite', 'inbound', 'outbound', 'rebagging', 'qc', 'users', 'settings', 'costView', 'corrections', 'warehouseApprove', 'currentWrite']),
  'Kepala Gudang': new Set(['inbound', 'outbound', 'costView', 'corrections', 'warehouseApprove', 'currentWrite']),
  Supervisor: new Set(['inbound', 'outbound', 'costView', 'currentWrite']),
  Pemantau: new Set(),
};

export const hasPermission = (role, permission) => {
  const canonical = canonicalRole(role);
  if (permission === 'view') return Boolean(canonical);
  if (permission === 'operations') {
    return hasPermission(canonical, 'inbound') || hasPermission(canonical, 'outbound');
  }
  if (permission === 'outboundPage') {
    return hasPermission(canonical, 'outbound') || hasPermission(canonical, 'costView');
  }
  if (permission === 'currentWrite') {
    return ROLE_PERMISSIONS[canonical]?.has('currentWrite') || false;
  }
  return ROLE_PERMISSIONS[canonical]?.has(permission) || false;
};

export const roleLabel = (role) => ROLE_LABELS[role] || ROLE_LABELS[canonicalRole(role)] || role || '—';
