import React, { useState } from 'react';
import { UploadCloud, FileSpreadsheet, Download, CheckCircle2 } from 'lucide-react';
import { useData } from '../context/DataContext';
import { apiError } from '../lib/api';
import { toast } from 'sonner';

const TEMPLATE = 'sku;nama;jumlah;kategori;satuan;harga_beli;harga_jual;supplier;lokasi\nB0010001X;CONTOH BERAS MEDIUM 5 KG;100;Beras;Kg;0;0;Nama Supplier;Gudang I\n';

const ImportData = () => {
  const { importCsv } = useData();
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);

  const process = async () => {
    if (!file) { toast.error('Pilih file terlebih dahulu'); return; }
    setBusy(true);
    try {
      const res = await importCsv(file);
      toast.success(`Import berhasil — ${res.inserted} SKU baru, ${res.updated} SKU diperbarui`);
      setFile(null);
    } catch (e) { toast.error(apiError(e)); }
    setBusy(false);
  };

  const downloadTemplate = () => {
    const blob = new Blob([TEMPLATE], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'template_import_sku.csv'; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6" data-testid="import-page">
      <div>
        <div className="label-mono mb-2">Master Data</div>
        <h1 className="font-display text-4xl font-bold">Import Data SKU</h1>
        <p className="text-[#8b93a1] mt-2 max-w-2xl">Unggah file CSV untuk menambahkan banyak produk sekaligus. SKU yang sudah ada akan diperbarui datanya. Gunakan template resmi agar kolom terbaca dengan benar.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card-surface p-6 lg:col-span-2">
          <label className="block border-2 border-dashed border-[#242f3d] rounded-2xl p-12 text-center cursor-pointer hover:border-[#2563eb] transition-colors">
            <input data-testid="import-file-input" type="file" accept=".csv" className="hidden" onChange={(e) => setFile(e.target.files[0])} />
            <UploadCloud size={44} className="mx-auto mb-4 text-[#60a5fa]" />
            <div className="font-display font-bold text-lg">{file ? file.name : 'Tarik & lepas file di sini'}</div>
            <div className="text-sm text-[#8b93a1] mt-1">atau klik untuk memilih file (.csv — maks 5MB)</div>
          </label>
          <button data-testid="import-process-btn" onClick={process} disabled={busy} className="btn-primary w-full mt-4 flex items-center justify-center gap-2 py-3 rounded-lg font-semibold text-sm disabled:opacity-60"><FileSpreadsheet size={16} /> {busy ? 'Memproses...' : 'Proses Import'}</button>
        </div>

        <div className="card-surface p-6">
          <h2 className="font-display text-lg font-bold mb-4">Panduan</h2>
          <ul className="space-y-3 text-sm text-[#aab4c4]">
            {['Pemisah kolom menggunakan titik koma (;)', 'Kolom wajib: sku, nama, jumlah, kategori, satuan', 'SKU yang sama akan diperbarui, bukan digandakan', 'Supplier baru otomatis ditambahkan'].map((t) => (
              <li key={t} className="flex items-start gap-2"><CheckCircle2 size={16} className="text-[#22c55e] mt-0.5 shrink-0" /> {t}</li>
            ))}
          </ul>
          <button data-testid="download-template-btn" onClick={downloadTemplate} className="w-full mt-5 inline-flex items-center justify-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg border border-[#242f3d] hover:bg-[#141a24]"><Download size={15} /> Unduh Template CSV</button>
        </div>
      </div>
    </div>
  );
};

export default ImportData;
