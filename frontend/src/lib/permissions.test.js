import {
  ROLE_LABELS,
  ROLE_PERMISSIONS,
  USER_ROLES,
  canonicalRole,
  hasPermission,
  roleDestination,
  roleLabel,
} from './permissions';

const expectedRoles = ['Administrator', 'Kepala Gudang', 'Supervisor', 'Operator', 'QC', 'Pemantau'];

test('uses exactly six selectable roles and stable labels', () => {
  expect(USER_ROLES).toEqual(expectedRoles);
  expect(ROLE_LABELS).toEqual({
    Administrator: 'Superadmin',
    'Kepala Gudang': 'Kepala Gudang',
    Supervisor: 'Admin Operasional',
    Operator: 'Petugas Bazar',
    QC: 'Petugas E-commerce',
    Pemantau: 'Viewer',
  });
});

test('legacy and business labels canonicalize consistently', () => {
  const aliases = {
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
  Object.entries(aliases).forEach(([input, expected]) => expect(canonicalRole(input)).toBe(expected));
  expect(canonicalRole('unknown-role')).toBe('Pemantau');
  expect(roleLabel('unknown-role')).toBe('Viewer');
});

test('permission matrix preserves the current role split', () => {
  expect([...ROLE_PERMISSIONS.Administrator]).toEqual(expect.arrayContaining(['users', 'settings', 'corrections', 'bazarOps', 'ecomOps']));
  expect(ROLE_PERMISSIONS['Kepala Gudang'].has('corrections')).toBe(true);
  expect(ROLE_PERMISSIONS.Supervisor.has('inbound')).toBe(true);
  expect(ROLE_PERMISSIONS.Supervisor.has('bazarOps')).toBe(false);
  expect(ROLE_PERMISSIONS.Operator.has('bazarOps')).toBe(true);
  expect(ROLE_PERMISSIONS.Operator.has('ecomOps')).toBe(false);
  expect(ROLE_PERMISSIONS.QC.has('ecomOps')).toBe(true);
  expect(ROLE_PERMISSIONS.QC.has('bazarOps')).toBe(false);
  expect(ROLE_PERMISSIONS.Pemantau.has('currentWrite')).toBe(false);
});

test('derived access and scoped destinations stay consistent', () => {
  expect(hasPermission('Superadmin', 'operations')).toBe(true);
  expect(hasPermission('Kepala Gudang', 'outboundPage')).toBe(true);
  expect(hasPermission('Admin Operasional', 'operations')).toBe(true);
  expect(hasPermission('Petugas Bazar', 'operations')).toBe(false);
  expect(hasPermission('Petugas E-commerce', 'operations')).toBe(false);
  expect(hasPermission('Viewer', 'view')).toBe(true);
  expect(hasPermission('Viewer', 'currentWrite')).toBe(false);
  expect(roleDestination('Petugas Bazar')).toBe('Gudang Bazar');
  expect(roleDestination('Petugas E-commerce')).toBe('Gudang E-commerce');
});
