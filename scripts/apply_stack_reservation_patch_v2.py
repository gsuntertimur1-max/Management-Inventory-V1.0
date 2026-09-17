from pathlib import Path
import runpy

p = Path('frontend/src/pages/CatatStok.jsx')
text = p.read_text()
current = '''const qty = Number(allocation.primaryQty || 0); const secondary = secondaryQty > 0 ? Math.floor(qty / secondaryQty) : 0; const remainder = secondaryQty > 0 ? qty - (secondary * secondaryQty) : 0; const packaging = secondaryQty > 0 ? ` · ${formatNum(secondary)} ${allocation.secondary || 'sekunder'}${remainder > 0 ? ` + ${formatNum(remainder)} ${allocation.unit || 'pcs'}` : ''}` : ''; const guide = fefoGuideFor(row.productId); const meta = fefoStackMeta(row.productId, allocation.stackCode); const priority = guide?.recommendedStacks?.includes(allocation.stackCode); const marker = priority ? (guide?.mode === 'FEFO_TRACKED' ? '★ FEFO' : '★ PRIORITAS') : (meta?.untrackedQty > 0 ? 'LEGACY' : (meta?.nextLot?.exp ? `EXP ${meta.nextLot.exp}` : '')); return <option key={allocation.id} value={allocation.stackCode}>{marker ? `${marker} · ` : ''}{allocation.stackCode} — sisa {formatNum(qty)} {allocation.unit || 'pcs'}{packaging}</option>;'''
normalized = '''const qty = Number(allocation.primaryQty || 0); const secondary = secondaryQty > 0 ? Math.floor(qty / secondaryQty) : 0; const remainder = secondaryQty > 0 ? qty - (secondary * secondaryQty) : 0; const packaging = secondaryQty > 0 ? ` · ${formatNum(secondary)} ${allocation.secondary || 'sekunder'}${remainder > 0 ? ` + ${formatNum(remainder)} ${allocation.unit || 'pcs'}` : ''}` : ''; const guide = fefoGuideFor(row.productId); const meta = fefoStackMeta(row.productId, allocation.stackCode); const recommended = guide?.recommendedStacks?.includes(allocation.stackCode); const expiry = meta?.nextLot?.exp ? ` · exp ${meta.nextLot.exp}` : (Number(meta?.untrackedQty || 0) > 0 ? ' · legacy' : ''); return <option key={allocation.id} value={allocation.stackCode}>{recommended ? '★ ' : ''}{allocation.stackCode} — sisa {formatNum(qty)} {allocation.unit || 'pcs'}{packaging}{expiry}</option>;'''
if current not in text:
    raise SystemExit('current FEFO option body not found')
p.write_text(text.replace(current, normalized, 1))
runpy.run_path('scripts/apply_stack_reservation_patch.py', run_name='__main__')
