// Six-role warehouse access model.
// Operator and QC remain internal storage codes for the scoped Bazar/E-commerce roles.
export const ROLE_LABELS = {
  Administrator: 'Superadmin',
  Superadmin: 'Superadmin',
  'Kepala Gudang': 'Kepala Gudang',
  Supervisor: 'Admin Operasional',
  Admin: 'Admin Operasional',
  'Admin Operasional': 'Admin Operasional',
  Operator: 'Petugas Bazar',
  'Petugas Bazar': 'Petugas Bazar',
  QC: 'Petugas E-commerce',
  'Petugas E-commerce': 'Petugas E-commerce',
  'Petugas Ecom': 'Petugas E-commerce',
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
  Operator: '#f59e0b',
  'Petugas Bazar': '#f59e0b',
  QC: '#0ea5e9',
  'Petugas E-commerce': '#0ea5e9',
  'Petugas Ecom': '#0ea5e9',
  Mandor: '#3b82f6',
  Pemantau: '#8b93a1',
  Viewer: '#8b93a1',
};

export const FOUR_ROLES = ['Administrator', 'Kepala Gudang', 'Supervisor', 'Operator', 'QC', 'Pemantau'];
export const USER_ROLES = FOUR_ROLES;

export const canonicalRole = (role) => ({
  Superadmin: 'Administrator',
  Admin: 'Supervisor',
  'Admin Operasional': 'Supervisor',
  'Petugas Bazar': 'Operator',
  'Petugas E-commerce': 'QC',
  'Petugas Ecom': 'QC',
  Mandor: 'Supervisor',
  Viewer: 'Pemantau',
}[role] || role || 'Pemantau');

const ROLE_PERMISSIONS = {
  Administrator: new Set(['mainInventory', 'masterWrite', 'inbound', 'outbound', 'rebagging', 'qc', 'users', 'settings', 'costView', 'corrections', 'warehouseApprove', 'currentWrite', 'bazarView', 'bazarOps', 'ecomView', 'ecomOps', 'consignmentView', 'consignmentHistory']),
  'Kepala Gudang': new Set(['mainInventory', 'inbound', 'outbound', 'costView', 'corrections', 'warehouseApprove', 'currentWrite', 'bazarView', 'bazarOps', 'ecomView', 'ecomOps', 'consignmentView', 'consignmentHistory']),
  Supervisor: new Set(['mainInventory', 'inbound', 'outbound', 'costView', 'currentWrite', 'bazarView', 'ecomView', 'consignmentView']),
  Operator: new Set(['bazarView', 'bazarOps', 'consignmentView', 'consignmentHistory']),
  QC: new Set(['ecomView', 'ecomOps', 'consignmentView', 'consignmentHistory']),
  Pemantau: new Set(['mainInventory', 'bazarView', 'ecomView', 'consignmentView']),
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
  return ROLE_PERMISSIONS[canonical]?.has(permission) || false;
};

export const roleDestination = (role) => {
  const canonical = canonicalRole(role);
  if (canonical === 'Operator') return 'Gudang Bazar';
  if (canonical === 'QC') return 'Gudang E-commerce';
  return '';
};

export const roleLabel = (role) => ROLE_LABELS[role] || ROLE_LABELS[canonicalRole(role)] || role || '—';
