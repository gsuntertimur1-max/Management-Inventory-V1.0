import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Clock, Loader, Maximize2, Minimize2, RefreshCw, Settings2, Volume2, VolumeX } from 'lucide-react';
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

const VOICE_PREF_KEY = 'pepeg_queue_voice_preferences_v1';

const voiceKey = (voice) => voice?.voiceURI || `${voice?.name || ''}|${voice?.lang || ''}`;

const loadVoicePreferences = () => {
  if (typeof window === 'undefined') return { voiceKey: '', rate: 0.85, pitch: 0.9 };
  try {
    const saved = JSON.parse(window.localStorage.getItem(VOICE_PREF_KEY) || '{}');
    const rate = Number(saved.rate);
    const pitch = Number(saved.pitch);
    return {
      voiceKey: String(saved.voiceKey || ''),
      rate: Number.isFinite(rate) ? Math.min(Math.max(rate, 0.6), 1.2) : 0.85,
      pitch: Number.isFinite(pitch) ? Math.min(Math.max(pitch, 0.6), 1.2) : 0.9,
    };
  } catch (error) {
    return { voiceKey: '', rate: 0.85, pitch: 0.9 };
  }
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
  const initialVoicePreferences = useMemo(() => loadVoicePreferences(), []);
  const [voiceOptions, setVoiceOptions] = useState([]);
  const [selectedVoiceKey, setSelectedVoiceKey] = useState(initialVoicePreferences.voiceKey);
  const [indonesianVoice, setIndonesianVoice] = useState(null);
  const [voiceRate, setVoiceRate] = useState(initialVoicePreferences.rate);
  const [voicePitch, setVoicePitch] = useState(initialVoicePreferences.pitch);
  const [showVoiceSettings, setShowVoiceSettings] = useState(false);
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
      setVoiceNotice('Fitur suara tidak didukung browser ini. Gunakan Chrome, Edge, atau Safari versi terbaru.');
      return undefined;
    }

    const loadBrowserVoices = () => {
      const voices = window.speechSynthesis.getVoices();
      const sorted = [...voices].sort((a, b) => {
        const aId = a.lang?.toLowerCase().startsWith('id') ? 0 : 1;
        const bId = b.lang?.toLowerCase().startsWith('id') ? 0 : 1;
        return aId - bId || String(a.name || '').localeCompare(String(b.name || ''));
      });
      setVoiceOptions(sorted);

      const saved = sorted.find((voice) => voiceKey(voice) === selectedVoiceKey);
      const automatic = sorted.find((voice) => voice.lang?.toLowerCase() === 'id-id')
        || sorted.find((voice) => voice.lang?.toLowerCase().startsWith('id'))
        || sorted.find((voice) => /bahasa indonesia|indonesian|damayanti|dimas/i.test(voice.name));
      const selected = saved || automatic || sorted[0] || null;

      setIndonesianVoice(selected);
      if (selected && voiceKey(selected) !== selectedVoiceKey) setSelectedVoiceKey(voiceKey(selected));
      if (selected) setVoiceNotice('');
      else if (voices.length > 0) setVoiceNotice('Suara browser tidak dapat dipilih. PEPEG akan mencoba suara bawaan.');
      else setVoiceNotice('Daftar suara browser belum dimuat. Tekan Aktifkan suara sekali untuk mengizinkan audio.');
    };

    loadBrowserVoices();
    window.speechSynthesis.addEventListener?.('voiceschanged', loadBrowserVoices);
    return () => window.speechSynthesis.removeEventListener?.('voiceschanged', loadBrowserVoices);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(VOICE_PREF_KEY, JSON.stringify({
      voiceKey: selectedVoiceKey,
      rate: voiceRate,
      pitch: voicePitch,
    }));
  }, [selectedVoiceKey, voiceRate, voicePitch]);

  const selectBrowserVoice = (key) => {
    setSelectedVoiceKey(key);
    const selected = voiceOptions.find((voice) => voiceKey(voice) === key) || null;
    setIndonesianVoice(selected);
    if (selected && !selected.lang?.toLowerCase().startsWith('id')) {
      setVoiceNotice('Voice ini bukan voice Bahasa Indonesia. Pelafalan nama lokasi/nomor mungkin terdengar berbeda.');
    } else {
      setVoiceNotice('');
    }
  };

  const speakText = useCallback((text, { immediate = false, onStart } = {}) => {
    if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
      setVoiceNotice('Fitur suara tidak didukung browser ini.');
      return false;
    }

    const synth = window.speechSynthesis;
    if (synth.paused) synth.resume();

    const message = new SpeechSynthesisUtterance(text);
    if (indonesianVoice) message.voice = indonesianVoice;
    message.lang = indonesianVoice?.lang || 'id-ID';
    message.rate = voiceRate;
    message.pitch = voicePitch;
    message.volume = 1;
    message.onstart = () => {
      setVoiceNotice('');
      onStart?.();
    };
    message.onerror = (event) => {
      if (event?.error !== 'interrupted' && event?.error !== 'canceled') {
        setVoiceNotice('Suara gagal diputar. Pastikan tab tidak dibisukan dan volume Windows aktif, lalu tekan Aktifkan suara lagi.');
      }
    };

    synth.cancel();
    const play = () => {
      if (synth.paused) synth.resume();
      synth.speak(message);
    };
    if (immediate) play();
    else window.setTimeout(play, 90);
    return true;
  }, [indonesianVoice, voiceRate, voicePitch]);

  useEffect(() => {
    if (!voiceEnabled || !('speechSynthesis' in window)) return;
    const nextLoad = loadingLoads.find((load) => load.antrian && !announcedQueuesRef.current.has(load.antrian));
    if (!nextLoad) return;

    const queueNumber = nextLoad.antrian;
    const spokenQueueNumber = String(queueNumber).replace(/[^a-zA-Z0-9]/g, '').split('').join(' ');
    const location = nextLoad.unit_loading && nextLoad.unit_loading !== '-'
      ? ` menuju ${nextLoad.unit_loading}`
      : ' menuju area pemuatan';

    speakText(
      `Nomor antrian ${spokenQueueNumber}. Silakan${location}.`,
      { onStart: () => announcedQueuesRef.current.add(queueNumber) },
    );
  }, [loadingLoads, speakText, voiceEnabled]);

  useEffect(() => {
    const activeQueueNumbers = new Set(active.map((load) => load.antrian).filter(Boolean));
    announcedQueuesRef.current = new Set([...announcedQueuesRef.current].filter((queue) => activeQueueNumbers.has(queue)));
  }, [active]);

  const enterPresentation = async () => {
    setPresentationMode(true);
    setVoiceEnabled(true);
    announcedQueuesRef.current = new Set();
    speakText('Suara antrian aktif.', { immediate: true });
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
    announcedQueuesRef.current = new Set();
    if (voiceEnabled) {
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      setVoiceEnabled(false);
      return;
    }

    setVoiceEnabled(true);
    speakText('Suara antrian aktif.', { immediate: true });
  };

  const testVoice = () => {
    setVoiceEnabled(true);
    speakText('Nomor antrian A 0 0 1. Silakan menuju Unit 18.', { immediate: true });
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
          <button type="button" onClick={() => setShowVoiceSettings((value) => !value)} className="queue-action inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#242f3d] px-3.5 py-2.5 text-sm text-[#c7d0dc] hover:bg-[#141a24]">
            <Settings2 size={18} /> Pengaturan suara
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

      {showVoiceSettings && (
        <div className="card-surface p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
            <div>
              <div className="font-semibold">Pengaturan Voice Browser</div>
              <div className="text-xs text-[#8b93a1] mt-1">Pilihan ini tersimpan hanya di browser/perangkat layar antrian ini.</div>
            </div>
            <button type="button" onClick={testVoice} className="inline-flex items-center gap-2 rounded-lg border border-[#2563eb] px-3 py-2 text-xs font-semibold text-[#93c5fd] hover:bg-[#2563eb]/10">
              <Volume2 size={14} /> Tes Suara
            </button>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(280px,1fr)_220px_220px] gap-4">
            <div>
              <label className="text-xs text-[#8b93a1] block mb-1.5">Voice</label>
              <select value={selectedVoiceKey} onChange={(event) => selectBrowserVoice(event.target.value)} className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5 text-sm outline-none focus:border-[#2563eb]">
                {voiceOptions.length === 0 && <option value="">Voice browser belum tersedia</option>}
                {voiceOptions.map((voice) => <option key={voiceKey(voice)} value={voiceKey(voice)}>
                  {voice.name} · {voice.lang}{voice.lang?.toLowerCase().startsWith('id') ? ' · Indonesia' : ''}
                </option>)}
              </select>
              <div className="text-[10px] text-[#64748b] mt-1.5">Voice Bahasa Indonesia ditempatkan paling atas. Daftar mengikuti voice yang terpasang di Windows/browser.</div>
            </div>
            <div>
              <div className="flex justify-between gap-3 mb-1.5"><label className="text-xs text-[#8b93a1]">Kecepatan</label><span className="font-mono text-xs text-[#93c5fd]">{Number(voiceRate).toFixed(2)}×</span></div>
              <input aria-label="Kecepatan suara" type="range" min="0.6" max="1.2" step="0.05" value={voiceRate} onChange={(event) => setVoiceRate(Number(event.target.value))} className="w-full" />
              <div className="text-[10px] text-[#64748b] mt-1">Lebih kecil = lebih tenang/lambat.</div>
            </div>
            <div>
              <div className="flex justify-between gap-3 mb-1.5"><label className="text-xs text-[#8b93a1]">Pitch / Nada</label><span className="font-mono text-xs text-[#93c5fd]">{Number(voicePitch).toFixed(2)}</span></div>
              <input aria-label="Pitch suara" type="range" min="0.6" max="1.2" step="0.05" value={voicePitch} onChange={(event) => setVoicePitch(Number(event.target.value))} className="w-full" />
              <div className="text-[10px] text-[#64748b] mt-1">Lebih kecil = nada lebih rendah/berat.</div>
            </div>
          </div>
          <div className="mt-3 text-[10px] text-[#8b93a1]">Saran awal suara pria formal: kecepatan 0,80–0,90 dan pitch 0,85–0,95. Karakter akhir tetap bergantung pada voice yang tersedia di perangkat.</div>
        </div>
      )}

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
