const standardZones = () => [{ code: 'A', count: 4 }, { code: 'B', count: 4 }, { code: 'C', count: 4 }];

export const DEFAULT_WAREHOUSES = [
  ...Array.from({ length: 8 }, (_, index) => ({ code: String(index + 17), name: `GBB ${index + 17}`, type: 'GBB', length: 50, width: 30, zones: standardZones(), active: true })),
  { code: 'MP1', name: 'MP1', type: 'MP', length: 230, width: 30, zones: [{ code: 'A', count: 8 }, { code: 'B', count: 8 }], active: true },
];

export const warehousesFromSettings = (warehouses) => Array.isArray(warehouses) && warehouses.length ? warehouses : DEFAULT_WAREHOUSES;

export const stackCodes = (warehouses) => warehousesFromSettings(warehouses)
  .filter((warehouse) => warehouse.active !== false)
  .flatMap((warehouse) => (warehouse.zones || []).flatMap((zone) => Array.from({ length: Number(zone.count || 0) }, (_, index) => `${warehouse.code}/${zone.code}${String(index + 1).padStart(2, '0')}`)));

export const zonesForWarehouse = (warehouse) => (warehouse?.zones || []).map((zone) => zone.code).reverse();
