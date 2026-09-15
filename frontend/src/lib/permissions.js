// Role values stored by the existing backend are kept for compatibility.
// The labels below are the names used in the warehouse workflow.
export const ROLE_LABELS = {
  Administrator: 'Superadmin',
  Supervisor: 'Admin Gudang',
  Operator: 'Operator Gudang',
  QC: 'QC',
  'Kepala Gudang': 'Kepala Gudang',
  Mandor: 'Mandor / Keuangan Operasional',
  Pemantau: 'Viewer / Auditor',
  Superadmin: 'Superadmin',
  Admin: 'Admin',
};

export const ROLE_COLORS = {
  Administrator: '#ef4444',
  Superadmin: '#ef4444',
  Supervisor: '#a855f7',
  Admin: '#a855f7',
  Operator: '#3b82f6',
  QC: '#22c55e',
  'Kepala Gudang': '#f59e0b',
  Mandor: '#14b8a6',
  Pemantau: '#8b93a1',
};

export const canonicalRole = (role) => ({
  Superadmin: 'Administrator',
  Admin: 'Supervisor',
}[role] || role || 'Pemantau');

const ROLE_PERMISSIONS = {
  Administrator: new Set(['masterWrite', 'inbound', 'outbound', 'rebagging', 'qc', 'users', 'settings', 'costView']),
  Supervisor: new Set(['masterWrite', 'inbound', 'outbound', 'costView']),
  Operator: new Set(['inbound', 'outbound']),
  QC: new Set(['qc']),
  'Kepala Gudang': new Set(['warehouseApprove']),
  Mandor: new Set(['costView']),
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
  // Current Railway branch exposes only master, inbound, outbound, and loading
  // write endpoints. Keep this separate from the future rebagging permission.
  if (permission === 'currentWrite') {
    return hasPermission(canonical, 'masterWrite')
      || hasPermission(canonical, 'inbound')
      || hasPermission(canonical, 'outbound');
  }
  return ROLE_PERMISSIONS[canonical]?.has(permission) || false;
};

export const roleLabel = (role) => ROLE_LABELS[role] || role || '—';
