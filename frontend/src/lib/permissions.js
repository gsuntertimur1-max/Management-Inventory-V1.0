// The backend keeps legacy storage values (Administrator/Supervisor/Pemantau)
// for compatibility. The UI exposes the workflow names requested by the
// warehouse: Superadmin/Admin/Operator/QC/Viewer.
export const ROLE_LABELS = {
  Administrator: 'Superadmin',
  Supervisor: 'Admin',
  Operator: 'Operator',
  QC: 'QC',
  Pemantau: 'Viewer',
  Viewer: 'Viewer',
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
  Pemantau: '#8b93a1',
  Viewer: '#8b93a1',
};

export const canonicalRole = (role) => ({
  Superadmin: 'Administrator',
  Admin: 'Supervisor',
  Pemantau: 'Viewer',
}[role] || role || 'Viewer');

const ROLE_PERMISSIONS = {
  Administrator: new Set(['masterWrite', 'inbound', 'mutasi', 'outbound', 'rebagging', 'qc', 'users', 'settings']),
  Supervisor: new Set(['inbound', 'mutasi', 'outbound']),
  Operator: new Set(['rebagging']),
  QC: new Set(['qc']),
  Viewer: new Set(),
};

export const hasPermission = (role, permission) => {
  const canonical = canonicalRole(role);
  if (permission === 'view') return Boolean(ROLE_PERMISSIONS[canonical]);
  if (permission === 'operations') {
    return ['inbound', 'mutasi', 'outbound'].some((item) => hasPermission(canonical, item));
  }
  // This is the permission used by the current shared transaction button.
  // It intentionally excludes master-data writes.
  if (permission === 'currentWrite') {
    return hasPermission(canonical, 'inbound')
      || hasPermission(canonical, 'mutasi')
      || hasPermission(canonical, 'outbound');
  }
  return ROLE_PERMISSIONS[canonical]?.has(permission) || false;
};

export const roleLabel = (role) => ROLE_LABELS[canonicalRole(role)] || role || '—';
