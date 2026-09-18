// Six-role warehouse access model.
// Canonical storage codes are retained for backward compatibility; UI labels
// expose only the current business-role names.

export const SIX_ROLES = ['Administrator', 'Kepala Gudang', 'Supervisor', 'Operator', 'QC', 'Pemantau'];
export const USER_ROLES = SIX_ROLES;
// Backward-compatible export for older imports. New code should use USER_ROLES.
export const FOUR_ROLES = SIX_ROLES;

export const ROLE_LABELS = {
  Administrator: 'Superadmin',
  'Kepala Gudang': 'Kepala Gudang',
  Supervisor: 'Admin Operasional',
  Operator: 'Petugas Bazar',
  QC: 'Petugas E-commerce',
  Pemantau: 'Viewer',
};

export const ROLE_COLORS = {
  Administrator: '#ef4444',
  'Kepala Gudang': '#f59e0b',
  Supervisor: '#3b82f6',
  Operator: '#f59e0b',
  QC: '#0ea5e9',
  Pemantau: '#8b93a1',
};

const ROLE_ALIASES = {
  Administrator: 'Administrator',
  Superadmin: 'Administrator',
  'Kepala Gudang': 'Kepala Gudang',
  Supervisor: 'Supervisor',
  Admin: 'Supervisor',
  'Admin Operasional': 'Supervisor',
  Mandor: 'Supervisor',
  Operator: 'Operator',
  'Petugas Bazar': 'Operator',
  QC: 'QC',
  'Petugas E-commerce': 'QC',
  'Petugas Ecom': 'QC',
  Pemantau: 'Pemantau',
  Viewer: 'Pemantau',
  'Viewer / Auditor': 'Pemantau',
};

export const canonicalRole = (role) => ROLE_ALIASES[String(role || '').trim()] || 'Pemantau';

export const ROLE_PERMISSIONS = {
  Administrator: new Set([
    'mainInventory', 'masterWrite', 'inbound', 'outbound', 'rebagging', 'qc', 'users',
    'settings', 'costView', 'corrections', 'warehouseApprove', 'currentWrite',
    'bazarView', 'bazarOps', 'ecomView', 'ecomOps', 'consignmentView', 'consignmentHistory',
  ]),
  'Kepala Gudang': new Set([
    'mainInventory', 'inbound', 'outbound', 'costView', 'corrections', 'warehouseApprove',
    'currentWrite', 'bazarView', 'bazarOps', 'ecomView', 'ecomOps',
    'consignmentView', 'consignmentHistory',
  ]),
  Supervisor: new Set([
    'mainInventory', 'inbound', 'outbound', 'costView', 'currentWrite',
    'bazarView', 'ecomView', 'consignmentView',
  ]),
  Operator: new Set(['bazarView', 'bazarOps', 'consignmentView', 'consignmentHistory']),
  QC: new Set(['ecomView', 'ecomOps', 'consignmentView', 'consignmentHistory']),
  Pemantau: new Set(['mainInventory', 'bazarView', 'ecomView', 'consignmentView']),
};

export const hasPermission = (role, permission) => {
  const canonical = canonicalRole(role);
  if (permission === 'view') return Boolean(ROLE_PERMISSIONS[canonical]);
  if (permission === 'operations') {
    return ROLE_PERMISSIONS[canonical]?.has('inbound') || ROLE_PERMISSIONS[canonical]?.has('outbound') || false;
  }
  if (permission === 'outboundPage') {
    return ROLE_PERMISSIONS[canonical]?.has('outbound') || ROLE_PERMISSIONS[canonical]?.has('costView') || false;
  }
  return ROLE_PERMISSIONS[canonical]?.has(permission) || false;
};

export const roleDestination = (role) => {
  const canonical = canonicalRole(role);
  if (canonical === 'Operator') return 'Gudang Bazar';
  if (canonical === 'QC') return 'Gudang E-commerce';
  return '';
};

export const roleLabel = (role) => ROLE_LABELS[canonicalRole(role)] || 'Viewer';
