import React from 'react';
import { ClipboardCheck, FileText, ShieldCheck } from 'lucide-react';
import { useData } from '../context/DataContext';
import { formatDate, formatNum } from '../mock';

const configs = {
  repacking: {
    eyebrow: 'Produksi / Rebagging',
    title: 'Repacking',
    note: 'Catat bahan baku, hasil produksi, TM hasil, batch, expired, susut, operator, dan status QC.',
    fields: ['TM Hasil', 'Produk Asal', 'Jumlah Bahan', 'Produk Hasil', 'Jumlah Hasil', 'Batch Hasil', 'Expired', 'Operator'],
    checks: ['Bahan baku tidak boleh melebihi stok BAIK', 'Hasil masuk ON_PROSES sampai QC lulus', 'Susut dihitung dari bahan dikurangi hasil'],
  },
  qc: {
    eyebrow: 'Quality Control',
    title: 'QC',
    note: 'Pemeriksaan bahan dan hasil repacking dengan status Lulus, Tidak Lulus, Pending, alasan reject, dan approval.',
    fields: ['Nomor Batch', 'TM Hasil', 'Produk', 'Pemeriksa', 'Status QC', 'Alasan Reject', 'Lampiran', 'Approval'],
    checks: ['QC dapat review repacking dan opname', 'Produk reject masuk RUSAK atau ON_PROSES', 'Semua approval tercatat audit'],
  },
  gudang: {
    eyebrow: 'Master Lokasi',
    title: 'Master Gudang',
    note: 'Pengaturan gudang, zona, kapasitas, kode tumpukan, dan status aktif.',
    fields: ['Kode Gudang', 'Nama Gudang', 'Tipe', 'Lokasi', 'Kapasitas', 'Zona', 'Status', 'Catatan'],
    checks: ['Kode tumpukan konsisten seperti 17/A01', 'Zona yang dipakai transaksi tidak dihapus', 'Perubahan masuk audit'],
  },
  treatment: {
    eyebrow: 'Pengendalian Hama',
    title: 'Spraying & Fumigasi',
    note: 'Spraying rutin 1 bulan; fumigasi beras 3 bulan durasi 10 hari; fumigasi sulfur durasi 3 hari.',
    fields: ['Jenis Treatment', 'Gudang', 'Tumpukan', 'Tanggal Mulai', 'Tanggal Selesai', 'Petugas', 'Alasan Percepatan', 'Catatan'],
    checks: ['Spraying berlaku untuk GBB', 'Fumigasi hanya untuk beras per tumpukan', 'Riwayat tampil di kartu tumpukan'],
  },
  retur: {
    eyebrow: 'Dokumen Pengeluaran',
    title: 'Retur',
    note: 'Retur wajib mengacu dokumen asal dan tidak boleh melebihi kuantitas dokumen.',
    fields: ['Dokumen Asal', 'Nomor Retur', 'SKU', 'Qty Retur', 'Kondisi', 'Lokasi Masuk', 'Alasan', 'Petugas'],
    checks: ['Tidak boleh melebihi dokumen asal', 'Stok kembali sesuai kondisi', 'Dokumen retur masuk riwayat'],
  },
  suratjalan: {
    eyebrow: 'Administrasi Muat',
    title: 'Surat Jalan',
    note: 'Surat jalan dibuat setelah selesai muat dan mengikuti dokumen SO/TM/CT/ND/Memo.',
    fields: ['Nomor Dokumen', 'Penerima', 'Nomor Polisi', 'Pengambil/Sopir', 'Tujuan', 'Jenis Dokumen', 'Tanggal Muat', 'Status'],
    checks: ['Nomor dokumen unik', 'Stok berkurang saat selesai muat', 'PDF bisa diunduh dari riwayat'],
  },
};

const WorkflowModule = ({ type }) => {
  const { transactions, monitoringStock, stackTreatments, suratJalan } = useData();
  const config = configs[type] || configs.repacking;
  const sourceRows = type === 'treatment' ? stackTreatments : type === 'suratjalan' ? suratJalan : transactions;

  return (
    <div className="space-y-6">
      <div><div className="label-mono mb-2">{config.eyebrow}</div><h1 className="font-display text-3xl md:text-4xl font-bold">{config.title}</h1><p className="text-[#8b93a1] mt-2 max-w-3xl">{config.note}</p></div>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-6">
        <div className="card-surface p-6">
          <h2 className="font-display text-xl font-bold mb-4 flex items-center gap-2"><ClipboardCheck size={20} /> Form {config.title}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {config.fields.map((field) => <div key={field}><label className="text-sm block mb-1">{field}</label><input className="w-full bg-[#0b0f17] border border-[#242f3d] rounded-lg px-3 py-2.5" placeholder={field} /></div>)}
          </div>
          <button className="btn-primary mt-5 px-5 py-2.5 rounded-xl" onClick={() => alert(`${config.title} siap disambungkan ke submit produksi`)}>Simpan {config.title}</button>
        </div>
        <div className="card-surface p-6">
          <h2 className="font-display text-xl font-bold mb-4 flex items-center gap-2"><ShieldCheck size={20} /> Validasi</h2>
          <div className="space-y-3">{config.checks.map((item) => <div key={item} className="rounded-lg bg-[#0b0f17] border border-[#1a222e] p-3 text-sm">{item}</div>)}</div>
          <div className="mt-4 rounded-lg bg-[#0d1728] border border-[#1f3657] p-3 text-xs text-[#93c5fd]">Saldo referensi monitoring: {formatNum(monitoringStock.length)} baris.</div>
        </div>
      </div>
      <div className="card-surface p-6">
        <h2 className="font-display text-xl font-bold mb-4 flex items-center gap-2"><FileText size={20} /> Riwayat Terkait</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tbl">
            <thead><tr className="text-left border-b border-[#1a222e]"><th className="py-2.5 pr-4">Waktu</th><th className="py-2.5 pr-4">Dokumen/Jenis</th><th className="py-2.5 pr-4">Produk/Lokasi</th><th className="py-2.5 pr-4">Qty/Status</th><th className="py-2.5">Petugas</th></tr></thead>
            <tbody>
              {sourceRows.slice(0, 12).map((row) => <tr key={row.id || row.no} className="tbl-row border-b border-[#131a24]"><td className="py-3 pr-4 font-mono text-xs">{formatDate(row.time || row.startDate || row.created_at)}</td><td className="py-3 pr-4">{row.ref || row.no || row.type || '-'}</td><td className="py-3 pr-4">{row.product || row.productName || row.stackCode || row.party || '-'}</td><td className="py-3 pr-4 font-mono">{row.qty || row.change || row.status || '-'}</td><td className="py-3">{row.operator || row.created_by || '-'}</td></tr>)}
              {sourceRows.length === 0 && <tr><td colSpan={5} className="py-8 text-center text-[#8b93a1]">Belum ada riwayat.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default WorkflowModule;
