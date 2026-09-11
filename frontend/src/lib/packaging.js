const asNumber = (value) => Number(value || 0);

export const quantityFromInput = (value, mode, product) => {
  const input = asNumber(value);
  if (input <= 0) return 0;
  if (mode === 'WEIGHT') {
    const unitWeight = asNumber(product?.weight);
    return unitWeight > 0 ? Number((input / unitWeight).toFixed(6)) : 0;
  }
  return input;
};

export const packagingBreakdown = (qty, product) => {
  const quantity = asNumber(qty);
  const perSecondary = asNumber(product?.secondaryQty);
  if (quantity <= 0 || perSecondary <= 0 || !product?.secondary) return null;
  const full = Math.floor((quantity + 1e-9) / perSecondary);
  const remainder = Number((quantity - (full * perSecondary)).toFixed(6));
  return { full, remainder: Math.max(remainder, 0), perSecondary };
};

export const quantityIsValid = (qty, product) => {
  if (asNumber(qty) <= 0) return false;
  if (asNumber(product?.secondaryQty) > 0 && Math.abs(asNumber(qty) - Math.round(asNumber(qty))) > 1e-6) return false;
  return true;
};

export const packagingText = (qty, product, formatNumber = (value) => value) => {
  const breakdown = packagingBreakdown(qty, product);
  if (!breakdown) return '';
  return `${formatNumber(breakdown.full)} ${product.secondary} penuh + ${formatNumber(breakdown.remainder)} ${product.unit}`;
};

export const totalWeight = (qty, product) => Number((asNumber(qty) * asNumber(product?.weight)).toFixed(6));
