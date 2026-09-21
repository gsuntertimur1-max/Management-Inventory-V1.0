import React, { useEffect, useState } from 'react';
import { AlertTriangle, ClipboardCheck, FileClock, Layers3, ReceiptText, RefreshCcw, Route, TimerReset } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/api';
import { useData } from '../context/DataContext';
import { hasPermission } from '../lib/permissions';

const Card = ({ icon: Icon, label, value, tone = '#93c5fd', onClick }) => (
  <button type="button" onClick={onClick} className="card-surface p-4 text-left hover:border-[#3b82f6]/60 transition-colors disabled:cursor-default w-full">
    <div className="flex items-start justify-between gap-3">
      <div><div className="label-mono text-[9px]">{label}</div><div className="font-mono text-2xl font-bold mt-1">{value ?? '—'}</div></div>
      <Icon size={18} style={{ color: tone }} />
    </div>
  </button>
);

const OperationalOutstandingPanel = () => {
  const navigate = useNavigate();
  const { user } = useData();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data: result } = await api.get('/dashboard-operations');
      setData(result || {});
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (!data || data.scope !== 'MAIN') {
    if (data?.scope && data.scope !== 'MAIN') {
      return <section className="card-surface p-4">
        <div className="flex items-center justify-between gap-3">
          <div><div className="label-mono text-[10px]">Outstanding Area Kerja</div><div className="text-sm mt-1">Stock opname konsinyasi aktif</div></div>
          <div className="font-mono text-2xl font-bold text-[#fbbf24]">{data.consignmentOpnamesPending || 0}</div>
        </div>
      </section>;
    }
    return null;
  }

  const cards = [
    ['SO Outstanding', data.soOutstanding, Route, '#f59e0b', '/monitoring-so', 'outboundPage'],
    ['Antrean Aktif', data.activeQueue, TimerReset, '#60a5fa', '/pengeluaran', 'outboundPage'],
    ['CT/Memo/ND Terbuka', data.pendingDocuments, FileClock, '#f59e0b', '/pengeluaran', 'outboundPage'],
    ['Pembayaran Muat', data.loadingPaymentsPending, ReceiptText, '#ef4444', '/riwayat', 'costView'],
    ['Opname Pending', data.opnamesPending, ClipboardCheck, '#a78bfa', '/opname-gudang', 'mainInventory'],
    ['Susunan Perlu Update', data.arrangementPending, Layers3, '#f59e0b', '/tumpukan', 'mainInventory'],
    ['Post-commit Open', data.postCommitOpen, AlertTriangle, '#ef4444', '/kontrol-integritas', 'masterWrite'],
  ].filter(([, value, , , , permission]) => value !== null && value !== undefined && hasPermission(user?.role, permission));

  return <section className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="label-mono">Outstanding Operasional</div>
      <button type="button" onClick={load} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-[#243044] px-3 py-2 text-xs text-[#93c5fd] disabled:opacity-50">
        <RefreshCcw size={13} className={loading ? 'animate-spin' : ''}/> Refresh
      </button>
    </div>
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3">
      {cards.map(([label, value, Icon, tone, path]) => <Card key={label} label={label} value={value} icon={Icon} tone={tone} onClick={() => navigate(path)} />)}
    </div>
  </section>;
};

export default OperationalOutstandingPanel;
