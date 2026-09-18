export const CONSIGNMENT_STACK_CODES = {
  'Gudang Bazar': ['18/A01-BAZAR', '18/A02-BAZAR', '18/A03-BAZAR', '18/A04-BAZAR'],
  'Gudang E-commerce': ['18/B01(1/2)-ECOM', '18/B02(1/2)-ECOM', '18/B03(1/2)-ECOM', '18/B04(1/2)-ECOM'],
};

export const consignmentStackCodes = (destination) => CONSIGNMENT_STACK_CODES[destination] || [];
export const defaultConsignmentStack = (destination) => consignmentStackCodes(destination)[0] || '';
export const consignmentAreaLabel = (destination) => destination === 'Gudang Bazar'
  ? '18/A01–18/A04 · BAZAR'
  : destination === 'Gudang E-commerce'
    ? '18/B01(1/2)–18/B04(1/2) · ECOM'
    : '';
