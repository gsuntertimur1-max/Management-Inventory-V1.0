import React, { useEffect, useMemo, useState } from 'react';
import { Activity, Boxes, Link2, Plus, RefreshCcw, ShieldCheck } from 'lucide-react';
import api, { apiError } from '../lib/api';
import { toast } from 'sonner';
import { useData } from '../context/DataContext';
import { hasPermission } from '../lib/permissions';

const inputCls = 'w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]';
const tabs = ['Akun', 'Mapping SKU', 'Sinkron Stok', 'Log'];

const MarketplaceIntegration = () => {
  const { user } = useData();
  const canManage = hasPermission(user?.role, 'ecomOps');
  const [activeTab, setActiveTab] = useState('Akun');
  const [accounts, setAccounts] = useState([]);
  const [products, setProducts] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [preview, setPreview] = useState([]);
  const [logs, setLogs] = useState([]);
  const [webhooks, setWebhooks] = useState([]);
  const [selectedAccount, setSelectedAccount] = useState('');
  const [saving, setSaving] = useState(false);

  const [accountForm, setAccountForm] = useState({
    provider: 'Shopee', shopName: '', shopId: '', connectionMode: 'API', note: '',
  });
  const [mappingForm, setMappingForm] = useState({
    accountId: '', productId: '', marketplaceSku: '', listingId: '',
  });

  const loadAll = async () => {
    const [a, p, m, l, w] = await Promise.all([
      api.get('/marketplace/accounts'),
      api.get('/marketplace/products'),
      api.get('/marketplace/sku-mappings'),
      api.get('/marketplace/sync-logs?limit=500'),
      api.get('/marketplace/webhook-events'),
    ]);
    setAccounts(a.data);
    setProducts(p.data);
    setMappings(m.data);
    setLogs(l.data);
    setWebhooks(w.data);
    if (!selectedAccount && a.data.length) setSelectedAccount(a.data[0].id);
  };

  useEffect(() => { loadAll().catch(() => {}); }, []);

  const accountMap = useMemo(() => Object.fromEntries(accounts.map((x) => [x.id, x])), [accounts]);
  const productMap = useMemo(() => Object.fromEntries(products.map((x) => [x.id, x])), [products]);

  const createAccount = async () => {
    if (!accountForm.shopName.trim()) return toast.error('Nama toko wajib diisi');
    setSaving(true);
    try {
      await api.post('/marketplace/accounts', accountForm);
      toast.success('Akun marketplace disimpan. Status tetap belum terhubung sampai kredensial API dipasang di Railway.');
      setAccountForm({ provider: 'Shopee', shopName: '', shopId: '', connectionMode: 'API', note: '' });
      await loadAll();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const toggleAccount = async (account) => {
    try {
      await api.patch('/marketplace/accounts/' + account.id, { active: !account.active });
      toast.success(account.active ? 'Akun dinonaktifkan' : 'Akun diaktifkan');
      await loadAll();
    } catch (e) { toast.error(apiError(e)); }
  };

  const saveMapping = async () => {
    if (!mappingForm.accountId || !mappingForm.productId || !mappingForm.marketplaceSku.trim()) {
      return toast.error('Akun, produk internal dan SKU marketplace wajib diisi');
    }
    setSaving(true);
    try {
      await api.post('/marketplace/sku-mappings', mappingForm);
      toast.success('Mapping SKU tersimpan');
      setMappingForm((p) => ({ ...p, productId: '', marketplaceSku: '', listingId: '' }));
      await loadAll();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const loadPreview = async (accountId, logPreview = false) => {
    if (!accountId) return toast.error('Pilih akun marketplace');
    try {
      if (logPreview) {
        await api.post('/marketplace/accounts/' + accountId + '/sync-preview');
        toast.success('Preview sinkron dibuat. Belum ada stok yang dikirim ke marketplace.');
      }
      const res = await api.get('/marketplace/stock-preview?accountId=' + encodeURIComponent(accountId));
      setPreview(res.data);
      setSelectedAccount(accountId);
      if (logPreview) await loadAll();
    } catch (e) { toast.error(apiError(e)); }
  };

  const tabButton = (tab) => (
    <button
      key={tab}
      onClick={() => setActiveTab(tab)}
      className={'px-4 py-2 rounded-lg text-sm font-semibold border ' + (activeTab === tab ? 'border-[#3b82f6] bg-[#2563eb]/15 text-[#93c5fd]' : 'border-[#243044] text-[#94a3b8]')}
    >
      {tab}
    </button>
  );

  return <div className="space-y-6">
    <div>
      <div className="label-mono mb-2">E-commerce · Integrasi Marketplace</div>
      <h1 className="font-display text-3xl sm:text-4xl font-bold">Marketplace Integration</h1>
      <p className="text-[#8b93a1] mt-2 text-sm">
        Inventory E-commerce tetap menjadi master stock. Kredensial API tidak disimpan di source code; konektor eksternal memakai environment Railway dan Marketplace Gateway.
      </p>
    </div>

    <div className="flex flex-wrap gap-2">{tabs.map(tabButton)}</div>

    {activeTab === 'Akun' && <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      {canManage && <section className="card-surface p-5 space-y-3">
        <div className="font-semibold flex items-center gap-2"><Link2 size={17}/> Tambah Akun Marketplace</div>
        <select className={inputCls} value={accountForm.provider} onChange={(e) => setAccountForm({ ...accountForm, provider: e.target.value })}>
          <option>Shopee</option><option>Tokopedia & Shop</option><option>TikTok Shop</option><option>Other</option>
        </select>
        <input className={inputCls} placeholder="Nama toko" value={accountForm.shopName} onChange={(e) => setAccountForm({ ...accountForm, shopName: e.target.value })}/>
        <input className={inputCls} placeholder="Shop ID (jika sudah ada)" value={accountForm.shopId} onChange={(e) => setAccountForm({ ...accountForm, shopId: e.target.value })}/>
        <select className={inputCls} value={accountForm.connectionMode} onChange={(e) => setAccountForm({ ...accountForm, connectionMode: e.target.value })}>
          <option>API</option><option>Middleware</option><option>Manual</option>
        </select>
        <textarea className={inputCls} placeholder="Catatan" value={accountForm.note} onChange={(e) => setAccountForm({ ...accountForm, note: e.target.value })}/>
        <button disabled={saving} onClick={createAccount} className="btn-primary w-full py-2.5 rounded-lg font-semibold">
          {saving ? 'Menyimpan…' : 'Simpan Akun'}
        </button>
      </section>}

      <section className={"card-surface p-5 " + (canManage ? "xl:col-span-2" : "xl:col-span-3")}>
        <div className="flex items-center justify-between mb-4">
          <div className="font-semibold">Akun Terdaftar</div>
          <button onClick={loadAll} className="text-xs inline-flex items-center gap-1 text-[#93c5fd]"><RefreshCcw size={13}/> Refresh</button>
        </div>
        <div className="space-y-3">
          {accounts.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada akun marketplace.</div>}
          {accounts.map((account) => <div key={account.id} className="border border-[#243044] rounded-xl p-4">
            <div className="flex flex-wrap justify-between gap-3">
              <div>
                <div className="font-semibold">{account.provider} · {account.shopName}</div>
                <div className="text-xs text-[#8b93a1] mt-1">Shop ID: {account.shopId || '—'} · Mode {account.connectionMode}</div>
              </div>
              <div className="text-right">
                <div className={'text-xs font-semibold ' + (account.gatewayConfigured ? 'text-[#22c55e]' : 'text-[#f59e0b]')}>
                  Gateway {account.gatewayConfigured ? 'Siap' : 'Belum dikonfigurasi'}
                </div>
                <div className="text-xs text-[#8b93a1] mt-1">{account.connectionStatus || 'NOT_CONNECTED'}</div>
              </div>
            </div>
            <div className="mt-3 text-xs text-[#94a3b8]">
              Credential source: <span className="font-mono">{account.credentialSource}</span> · prefix <span className="font-mono">{account.credentialEnvPrefix}</span>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              <button onClick={() => { setSelectedAccount(account.id); setActiveTab('Mapping SKU'); setMappingForm((p) => ({ ...p, accountId: account.id })); }} className="px-3 py-2 rounded-lg border border-[#3b82f6]/40 text-[#93c5fd] text-xs font-semibold">Mapping SKU</button>
              <button onClick={() => { setActiveTab('Sinkron Stok'); loadPreview(account.id, false); }} className="px-3 py-2 rounded-lg border border-[#22c55e]/40 text-[#86efac] text-xs font-semibold">Preview Stok</button>
              {canManage && <button onClick={() => toggleAccount(account)} className="px-3 py-2 rounded-lg border border-[#64748b]/40 text-[#cbd5e1] text-xs font-semibold">{account.active ? 'Nonaktifkan' : 'Aktifkan'}</button>}
            </div>
          </div>)}
        </div>
      </section>
    </div>}

    {activeTab === 'Mapping SKU' && <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      {canManage && <section className="card-surface p-5 space-y-3">
        <div className="font-semibold flex items-center gap-2"><Boxes size={17}/> Mapping SKU</div>
        <select className={inputCls} value={mappingForm.accountId} onChange={(e) => setMappingForm({ ...mappingForm, accountId: e.target.value })}>
          <option value="">Pilih akun marketplace</option>
          {accounts.filter((x) => x.active).map((x) => <option key={x.id} value={x.id}>{x.provider} · {x.shopName}</option>)}
        </select>
        <select className={inputCls} value={mappingForm.productId} onChange={(e) => setMappingForm({ ...mappingForm, productId: e.target.value })}>
          <option value="">Pilih produk internal</option>
          {products.map((x) => <option key={x.id} value={x.id}>{x.sku} · {x.name}</option>)}
        </select>
        <input className={inputCls} placeholder="SKU marketplace" value={mappingForm.marketplaceSku} onChange={(e) => setMappingForm({ ...mappingForm, marketplaceSku: e.target.value })}/>
        <input className={inputCls} placeholder="Listing / Item ID (opsional)" value={mappingForm.listingId} onChange={(e) => setMappingForm({ ...mappingForm, listingId: e.target.value })}/>
        <button disabled={saving} onClick={saveMapping} className="btn-primary w-full py-2.5 rounded-lg font-semibold"><Plus size={16} className="inline mr-1"/> Simpan Mapping</button>
      </section>}

      <section className={"card-surface p-5 " + (canManage ? "xl:col-span-2" : "xl:col-span-3")}>
        <div className="font-semibold mb-4">Daftar Mapping</div>
        <div className="space-y-2 max-h-[560px] overflow-auto">
          {mappings.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada mapping SKU.</div>}
          {mappings.map((row) => <div key={row.id} className="border border-[#243044] rounded-xl p-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <div><b>{row.marketplaceSku}</b> → <span className="font-mono">{row.internalSku}</span> · {row.productName}</div>
              <span className="text-xs text-[#8b93a1]">{accountMap[row.accountId]?.provider || row.provider} · {accountMap[row.accountId]?.shopName || row.shopName}</span>
            </div>
            <div className="text-xs text-[#8b93a1] mt-1">Listing ID: {row.listingId || '—'} · {row.active ? 'Aktif' : 'Nonaktif'}</div>
          </div>)}
        </div>
      </section>
    </div>}

    {activeTab === 'Sinkron Stok' && <div className="space-y-4">
      <section className="card-surface p-5">
        <div className="flex flex-col md:flex-row md:items-end gap-3">
          <div className="flex-1">
            <label className="text-xs text-[#8b93a1]">Akun marketplace</label>
            <select className={inputCls} value={selectedAccount} onChange={(e) => { setSelectedAccount(e.target.value); loadPreview(e.target.value, false); }}>
              <option value="">Pilih akun</option>
              {accounts.map((x) => <option key={x.id} value={x.id}>{x.provider} · {x.shopName}</option>)}
            </select>
          </div>
          {canManage && <button onClick={() => loadPreview(selectedAccount, true)} className="btn-primary px-5 py-2.5 rounded-lg font-semibold">Buat Preview Sinkron</button>}
        </div>
        <div className="mt-3 flex items-start gap-2 text-xs text-[#fbbf24]"><ShieldCheck size={15} className="mt-0.5 shrink-0"/> Preview tidak mengirim atau mengubah stok marketplace. Push stok baru diaktifkan setelah konektor API resmi dan kredensial Railway tersedia.</div>
      </section>

      <section className="card-surface p-5 overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead><tr className="text-left text-[#8b93a1] border-b border-[#243044]">
            <th className="py-2 pr-3">SKU Marketplace</th><th className="py-2 pr-3">Produk Internal</th><th className="py-2 pr-3">Fisik</th><th className="py-2 pr-3">Reserved</th><th className="py-2 pr-3">Available</th><th className="py-2">Qty yang akan dikirim</th>
          </tr></thead>
          <tbody>{preview.map((row) => <tr key={row.id} className="border-b border-[#1f2937]">
            <td className="py-3 pr-3 font-mono">{row.marketplaceSku}</td>
            <td className="py-3 pr-3">{row.internalSku} · {row.productName}</td>
            <td className="py-3 pr-3">{row.physicalQty} {row.unit}</td>
            <td className="py-3 pr-3">{row.reservedQty} {row.unit}</td>
            <td className="py-3 pr-3">{row.availableQty} {row.unit}</td>
            <td className="py-3 font-semibold text-[#86efac]">{row.recommendedMarketplaceQty} {row.unit}</td>
          </tr>)}</tbody>
        </table>
        {preview.length === 0 && <div className="text-sm text-[#8b93a1] py-6">Belum ada data preview. Pilih akun dan pastikan SKU sudah dimapping.</div>}
      </section>
    </div>}

    {activeTab === 'Log' && <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <section className="card-surface p-5">
        <div className="font-semibold flex items-center gap-2 mb-4"><Activity size={17}/> Sync Log</div>
        <div className="space-y-2 max-h-[560px] overflow-auto">
          {logs.map((row) => <div key={row.id} className="border-b border-[#1f2937] pb-2 text-xs">
            <div className={row.level === 'ERROR' ? 'text-[#fca5a5] font-semibold' : 'font-medium'}>{row.eventType} · {row.reference || '—'}</div>
            <div className="text-[#8b93a1]">{new Date(row.time).toLocaleString('id-ID')} · {row.provider || 'Internal'}</div>
            {row.message && <div className="text-[#cbd5e1] mt-1">{row.message}</div>}
          </div>)}
          {logs.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada log sinkronisasi.</div>}
        </div>
      </section>

      <section className="card-surface p-5">
        <div className="font-semibold flex items-center gap-2 mb-4"><Link2 size={17}/> Webhook / Gateway Events</div>
        <div className="space-y-2 max-h-[560px] overflow-auto">
          {webhooks.map((row) => <div key={row.id} className="border-b border-[#1f2937] pb-2 text-xs">
            <div className="font-medium">{row.eventType} · {row.orderNo}</div>
            <div className="text-[#8b93a1]">{row.provider} · {new Date(row.receivedAt).toLocaleString('id-ID')}</div>
            <div className={'mt-1 font-semibold ' + (row.status === 'PROCESSED' ? 'text-[#86efac]' : row.status === 'FAILED' ? 'text-[#fca5a5]' : 'text-[#fbbf24]')}>{row.status}</div>
            {row.error && <div className="text-[#fca5a5] mt-1">{row.error}</div>}
          </div>)}
          {webhooks.length === 0 && <div className="text-sm text-[#8b93a1]">Belum ada event gateway.</div>}
        </div>
      </section>
    </div>}

    <section className="card-surface p-5 text-xs text-[#94a3b8]">
      <div className="font-semibold text-[#e2e8f0] mb-2">Status integrasi</div>
      Fondasi gateway, akun, mapping SKU, stock preview, event idempotency dan log sudah tersedia. Koneksi langsung ke API marketplace tetap berstatus <b>NOT_CONNECTED</b> sampai App ID/secret/token resmi dipasang sebagai environment Railway dan adapter provider diaktifkan.
    </section>
  </div>;
};

export default MarketplaceIntegration;
