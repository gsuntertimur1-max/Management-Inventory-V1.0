import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Clock, Loader, Maximize2, Minimize2, RefreshCw, Volume2, VolumeX } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatNum } from '../mock';

const LayarAntrian = () => {
  const { outboundLoads, refreshOutboundLoads } = useData();
  const screenRef = useRef(null);
  const announcedQueueRef = useRef(null);
  const [presentationMode, setPresentationMode] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [indonesianVoice, setIndonesianVoice] = useState(null);
  const [voiceNotice, setVoiceNotice] = useState('');
  const [lastUpdated, setLastUpdated] = useState(new Date());
  const [refreshing, setRefreshing] = useState(false);
  const active = outboundLoads
    .filter((load) => load.status !== 'Selesai')
    .sort((a, b) => (a.antrian || '').localeCompare(b.antrian || ''));
  const loading = active.find((load) => load.status === 'Sedang Dimuat');

  const refreshQueue = useCallback(async () => {
    setRefreshing(true);
    try {
      await refreshOutboundLoads();
      setLastUpdated(new Date());
    } finally {
      setRefreshing(false);
    }
  }, [refreshOutboundLoads]);

  useEffect(() => {
    const intervalId = window.setInterval(refreshQueue, 60000);
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
    const queueNumber = loading?.antrian;
    if (!voiceEnabled || !indonesianVoice || !queueNumber || announcedQueueRef.current === queueNumber || !('speechSynthesis' in window)) return;

    window.speechSynthesis.cancel();
    const spokenQueueNumber = String(queueNumber).replace(/[^a-zA-Z0-9]/g, '').split('').join(' ');
    const message = new SpeechSynthesisUtterance(`Nomor antrian ${spokenQueueNumber}. Silakan menuju area pemuatan.`);
    message.voice = indonesianVoice;
    message.lang = indonesianVoice.lang || 'id-ID';
    message.rate = 0.85;
    message.volume = 1;
    window.speechSynthesis.speak(message);
    announcedQueueRef.current = queueNumber;
  }, [indonesianVoice, loading?.antrian, voiceEnabled]);

  const enterPresentation = async () => {
    setPresentationMode(true);
    setVoiceEnabled(true);
    announcedQueueRef.current = null;
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
    announcedQueueRef.current = null;
    setVoiceEnabled((enabled) => !enabled);
  };

  return (
    <div ref={screenRef} className={`${presentationMode ? 'fixed inset-0 z-[60] overflow-y-auto bg-[#070a10] p-4 sm:p-8' : ''} space-y-6`}>
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5 lg:gap-6">
        <div>
          <div className="label-mono mb-2">Monitor Pemuatan</div>
          <h1 className="font-display text-4xl font-bold">Layar Antrian Pemuatan</h1>
          <p className="text-[#8b93a1] mt-2">Nomor antrian reset setiap hari dan hanya menampilkan proses yang belum selesai.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <button type="button" onClick={toggleVoice} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#242f3d] px-3.5 py-2.5 text-sm text-[#c7d0dc] hover:bg-[#141a24]">
            {voiceEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
            {voiceEnabled ? 'Suara aktif' : 'Aktifkan suara'}
          </button>
          <button type="button" onClick={refreshQueue} disabled={refreshing} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#242f3d] px-3.5 py-2.5 text-sm text-[#c7d0dc] hover:bg-[#141a24] disabled:opacity-60">
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

      <div className="flex items-end justify-between gap-4 border-y border-[#161d29] py-4">
        <div className="text-xs text-[#6b7688]">Diperbarui otomatis setiap 1 menit · Terakhir {lastUpdated.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}</div>
        <div className="text-right shrink-0"><div className="label-mono">Sedang Dilayani</div><div className="font-display text-4xl sm:text-5xl font-bold text-[#60a5fa]">{loading ? loading.antrian : '—'}</div></div>
      </div>

      {loading && (
        <div className="card-surface p-8 relative overflow-hidden" style={{ background: 'linear-gradient(135deg, rgba(37,99,235,0.15), rgba(20,26,37,0.9))' }}>
          <div className="flex items-center gap-3 mb-2"><Loader size={20} className="text-[#3b82f6] animate-spin" /><span className="label-mono text-[#60a5fa]">Sedang Dimuat</span></div>
          <div className="font-display text-7xl font-bold mb-2">{loading.antrian}</div>
          <div className="text-xl font-semibold">{loading.party}</div>
          <div className="text-[#aab4c4] mt-1">{loading.ref || 'Tanpa referensi'} · {formatNum(loading.total_unit || 0)} unit · {formatNum(loading.total_berat || 0)} kg</div>
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
            <div className="label-mono text-[10px] mt-1">{load.ref || 'Tanpa referensi'} · {load.polisi || 'Tanpa no. polisi'}</div>
            <div className="mt-4 pt-4 border-t border-[#151d28] flex justify-between text-xs"><span className="text-[#8b93a1]">{formatNum((load.items || []).length)} jenis barang</span><span className="font-mono">{formatNum(load.total_unit || 0)} unit</span></div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default LayarAntrian;
