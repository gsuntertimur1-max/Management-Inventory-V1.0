import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Clock, Loader, Maximize2, Minimize2, RefreshCw, Volume2, VolumeX } from 'lucide-react';
import api from '../lib/api';
import { formatNum } from '../mock';

const quantitySummary = (items = []) => {
  const totals = {};
  items.forEach((item) => {
    const unit = item.unit || 'unit';
    totals[unit] = (totals[unit] || 0) + Number(item.qty || 0);
  });
  const parts = Object.entries(totals)
    .filter(([, value]) => Math.abs(value) > 1e-9)
    .map(([unit, value]) => `${formatNum(value)} ${unit}`);
  return parts.join(' + ') || '—';
};

const measureSummary = (items = []) => {
  const totals = {};
  items.forEach((item) => {
    const unit = item.measureUnit || 'kg';
    totals[unit] = (totals[unit] || 0) + Number(item.berat || 0);
  });
  const parts = Object.entries(totals)
    .filter(([, value]) => Math.abs(value) > 1e-9)
    .map(([unit, value]) => `${formatNum(value)} ${unit}`);
  return parts.join(' + ') || '—';
};

const LayarAntrian = () => {
  const screenRef = useRef(null);
  const announcedQueuesRef = useRef(new Set());
  const [queueLoads, setQueueLoads] = useState([]);
  const [presentationMode, setPresentationMode] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [indonesianVoice, setIndonesianVoice] = useState(null);
  const [voiceNotice, setVoiceNotice] = useState('');
  const [lastUpdated, setLastUpdated] = useState(new Date());
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState('');

  const active = useMemo(
    () => [...queueLoads].sort((a, b) => (a.antrian || '').localeCompare(b.antrian || '')),
    [queueLoads],
  );
  const loadingLoads = useMemo(
    () => active.filter((load) => load.status === 'Sedang Dimuat'),
    [active],
  );

  const refreshQueue = useCallback(async () => {
    setRefreshing(true);
    try {
      const { data } = await api.get('/outbound-queue');
      setQueueLoads(Array.isArray(data) ? data : []);
      setLastUpdated(new Date());
      setRefreshError('');
    } catch (error) {
      setRefreshError('Data antrian belum dapat diperbarui. Tampilan terakhir tetap dipertahankan.');
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refreshQueue();
    const intervalId = window.setInterval(refreshQueue, 30000);
    return () => window.clearInterval(intervalId);
  }, [refreshQueue]);

  useEffect(() => {
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) setPresentationMode(false);
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, []);

  useEffect(() => {
    if (!('speechSynthesis' in window)) {
      setVoiceNotice('Fitur suara tidak didukung browser ini. Gunakan Chrome atau Safari versi terbaru.');
      return undefined;
    }

    const loadIndonesianVoice = () => {
      const voices = window.speechSynthesis.getVoices();
      const selected = voices.find((voice) => voice.lang?.toLowerCase() === 'id-id')
        || voices.find((voice) => voice.lang?.toLowerCase().startsWith('id'))
        || voices.find((voice) => /bahasa indonesia|indonesian|damayanti|dimas/i.test(voice.name));

      setIndonesianVoice(selected || null);
      setVoiceNotice(selected ? '' : 'Suara Bahasa Indonesia belum tersedia. Tambahkan suara Bahasa Indonesia pada pengaturan perangkat, lalu buka kembali halaman ini.');
    };

    loadIndonesianVoice();
    window.speechSynthesis.addEventListener?.('voiceschanged', loadIndonesianVoice);
    return () => window.speechSynthesis.removeEventListener?.('voiceschanged', loadIndonesianVoice);
  }, []);

  useEffect(() => {
    if (!voiceEnabled || !indonesianVoice || !('speechSynthesis' in window)) return;
    const nextLoad = loadingLoads.find((load) => load.antrian && !announcedQueuesRef.current.has(load.antrian));
    if (!nextLoad) return;

    const queueNumber = nextLoad.antrian;
    const spokenQueueNumber = String(queueNumber).replace(/[^a-zA-Z0-9]/g, '').split('').join(' ');
    const location = nextLoad.unit_loading && nextLoad.unit_loading !== '-'
      ? ` menuju ${nextLoad.unit_loading}`
      : ' menuju area pemuatan';
    const message = new SpeechSynthesisUtterance(`Nomor antrian ${spokenQueueNumber}. Silakan${location}.`);
    message.voice = indonesianVoice;
    message.lang = indonesianVoice.lang || 'id-ID';
    message.rate = 0.85;
    message.volume = 1;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(message);
    announcedQueuesRef.current.add(queueNumber);
  }, [indonesianVoice, loadingLoads, voiceEnabled]);

  useEffect(() => {
    const activeQueueNumbers = new Set(active.map((load) => load.antrian).filter(Boolean));
    announcedQueuesRef.current = new Set([...announcedQueuesRef.current].filter((queue) => activeQueueNumbers.has(queue)));
  }, [active]);

  const enterPresentation = async () => {
    setPresentationMode(true);
    setVoiceEnabled(true);
    announcedQueuesRef.current = new Set();
    try {
      await screenRef.current?.requestFullscreen?.();
    } catch (error) {
      // Mode presentasi CSS tetap digunakan bila browser tidak mendukung Fullscreen API.
    }
  };

  const exitPresentation = async () => {
    setPresentationMode(false);
    if (document.fullscreenElement) await document.exitFullscreen?.();
  };

  const toggleVoice = () => {
    if (voiceEnabled && 'speechSynthesis' in window) window.speechSynthesis.cancel();
    announcedQueuesRef.current = new Set();
    setVoiceEnabled((enabled) => !enabled);
  };

  const loadingQueueLabel = loadingLoads.length
    ? loadingLoads.map((load) => load.antrian).filter(Boolean).join(' · ')
    : '—';

  return (
    <div ref={screenRef} className={`${presentationMode ? 'queue-fullscreen fixed inset-0 z-[60] overflow-y-auto bg-[#070a10] p-4 sm:p-8' : ''} space-y-6`}>
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5 lg:gap-6">
        <div>
          <div className="label-mono mb-2">Monitor Pemuatan</div>
          <h1 className="font-display text-4xl font-bold">Layar Antrian Pemuatan</h1>
          </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <button type="button" onClick={toggleVoice} className="queue-action inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#242f3d] px-3.5 py-2.5 text-sm text-[#c7d0dc] hover:bg-[#141a24]">
            {voiceEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
            {voiceEnabled ? 'Suara aktif' : 'Aktifkan suara'}
          </button>
          <button type="button" onClick={refreshQueue} disabled={refreshing} className="queue-action inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#242f3d] px-3.5 py-2.5 text-sm text-[#c7d0dc] hover:bg-[#141a24] disabled:opacity-60">
            <RefreshCw size={18} className={refreshing ? 'animate-spin' : ''} /> Perbarui
          </button>
          <button type="button" onClick={presentationMode ? exitPresentation : enterPresentation} className="btn-primary inline-flex min-h-11 items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm font-semibold">
            {presentationMode ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            {presentationMode ? 'Keluar fullscreen' : 'Tampilkan fullscreen'}
          </button>
        </div>
      </div>

      {voiceEnabled && voiceNotice && (
        <div role="status" className="rounded-xl border border-[#eab308]/30 bg-[#eab308]/10 px-4 py-3 text-sm text-[#facc15]">
          {voiceNotice}
        </div>
      )}
      {refreshError && (
        <div role="status" className="rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 px-4 py-3 text-sm text-[#fca5a5]">
          {refreshError}
        </div>
      )}

      <div className="flex items-end justify-between gap-4 border-y border-[#161d29] py-4">
        <div className="text-xs text-[#6b7688]">Diperbarui otomatis setiap 30 detik · Terakhir {lastUpdated.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}</div>
        <div className="text-right shrink-0"><div className="label-mono">Sedang Dilayani</div><div className="font-display text-3xl sm:text-5xl font-bold text-[#60a5fa]">{loadingQueueLabel}</div></div>
      </div>

      {loadingLoads.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {loadingLoads.map((loading) => (
            <div key={loading.id} className="queue-loading-card card-surface p-8 relative overflow-hidden">
              <div className="flex items-center gap-3 mb-2"><Loader size={20} className="text-[#3b82f6] animate-spin" /><span className="label-mono text-[#60a5fa]">Sedang Dimuat · {loading.unit_loading || '-'}</span></div>
              <div className="font-display text-6xl sm:text-7xl font-bold mb-2">{loading.antrian}</div>
              <div className="text-xl font-semibold">{loading.party}</div>
              <div className="text-[#aab4c4] mt-1">{(loading.documents || [loading.ref]).filter(Boolean).join(', ') || 'Tanpa referensi'}</div>
              <div className="text-sm text-[#8b93a1] mt-2">{quantitySummary(loading.items)} · {measureSummary(loading.items)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {active.length === 0 ? <div className="card-surface p-8 text-center text-[#6b7688] col-span-full">Tidak ada antrian aktif.</div> : active.map((load) => (
          <div key={load.id} className="card-surface stat-card p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="font-display text-4xl font-bold">{load.antrian}</div>
              {load.status === 'Menunggu'
                ? <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full" style={{ background: 'rgba(234,179,8,.15)', color: '#eab308' }}><Clock size={12} /> Menunggu</span>
                : <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full" style={{ background: 'rgba(59,130,246,.15)', color: '#3b82f6' }}><Loader size={12} className="animate-spin" /> Dimuat</span>}
            </div>
            <div className="font-semibold">{load.party}</div>
            <div className="label-mono text-[10px] mt-1">{(load.documents || [load.ref]).filter(Boolean).join(', ') || 'Tanpa referensi'} · {load.polisi || 'Tanpa no. polisi'}</div>
            <div className="text-xs text-[#60a5fa] mt-1">Lokasi muat: {load.unit_loading || '-'}</div>
            <div className="mt-4 pt-4 border-t border-[#151d28] space-y-1 text-xs">
              <div className="flex justify-between gap-3"><span className="text-[#8b93a1]">{formatNum((load.items || []).length)} jenis barang</span><span className="font-mono text-right">{quantitySummary(load.items)}</span></div>
              <div className="text-right font-mono text-[#6b7688]">{measureSummary(load.items)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default LayarAntrian;
