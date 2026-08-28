import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { angka, rupiah } from "@/lib/format";
import type {
  ImportMode,
  ProductImportRequest,
  ProductImportResult,
  ProductImportRow,
  Supplier,
} from "@/lib/types";

const HEADERS = [
  "sku",
  "nama",
  "jumlah",
  "kategori",
  "satuan",
  "harga_beli",
  "harga_jual",
  "supplier",
  "lokasi",
];

const TEMPLATE = `${HEADERS.join(",")}
ELEC-KBD-200,Keyboard Mekanikal RGB,45,Elektronik & Gadget,Pcs,420000,589000,PT Mega Nusantara Distribusi,Rak A-05
OFF-STP-010,Stapler Besar HD-50,80,Peralatan Kantor,Pcs,68000,95000,CV Sumber Makmur Logistik,Rak B-03
FNB-TEA-500,Teh Celup Premium 500gr,150,F&B / Bahan Makanan,Pack,42000,56000,PT Agro Indo Sejahtera,Rak C-04`;

const MODE_LABELS: Record<string, string> = {
  add: "Tambahkan ke stok yang ada",
  replace: "Ganti jumlah stok (timpa)",
};

const NUM = (v: string | undefined): number | null => {
  if (v === undefined) return null;
  const cleaned = v.replace(/[^0-9.,-]/g, "").replace(/\.(?=\d{3}\b)/g, "").replace(",", ".");
  if (cleaned.trim() === "") return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
};

/** Split a CSV line honouring double-quoted fields. */
function splitLine(line: string): string[] {
  const out: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        field += '"';
        i += 1;
      } else quoted = !quoted;
    } else if ((ch === "," || ch === ";" || ch === "\t") && !quoted) {
      out.push(field);
      field = "";
    } else field += ch;
  }
  out.push(field);
  return out.map((f) => f.trim());
}

function parseRows(text: string): { rows: ProductImportRow[]; problems: string[] } {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  const rows: ProductImportRow[] = [];
  const problems: string[] = [];
  if (lines.length === 0) return { rows, problems };

  let startIdx = 0;
  let map: Record<string, number> = { sku: 0, nama: 1, jumlah: 2, kategori: 3, satuan: 4, harga_beli: 5, harga_jual: 6, supplier: 7, lokasi: 8 };

  const first = splitLine(lines[0]).map((h) => h.toLowerCase());
  const looksLikeHeader = first.some((h) => h === "sku" || h.includes("kode"));
  if (looksLikeHeader) {
    startIdx = 1;
    const found: Record<string, number> = {};
    first.forEach((h, i) => {
      if (h.includes("sku") || h.includes("kode")) found.sku = i;
      else if (h.includes("nama") || h.includes("barang") || h.includes("produk")) found.nama = i;
      else if (h.includes("jumlah") || h.includes("stok") || h.includes("qty")) found.jumlah = i;
      else if (h.includes("kategori")) found.kategori = i;
      else if (h.includes("satuan") || h.includes("unit")) found.satuan = i;
      else if (h.includes("beli") || h.includes("modal")) found.harga_beli = i;
      else if (h.includes("jual")) found.harga_jual = i;
      else if (h.includes("supplier") || h.includes("vendor")) found.supplier = i;
      else if (h.includes("lokasi") || h.includes("rak")) found.lokasi = i;
    });
    map = { ...map, ...found };
  }

  for (let i = startIdx; i < lines.length; i += 1) {
    const cells = splitLine(lines[i]);
    const sku = (cells[map.sku] ?? "").trim();
    if (!sku) {
      problems.push(`Baris ${i + 1}: kode SKU kosong — baris dilewati`);
      continue;
    }
    const qty = NUM(cells[map.jumlah]);
    rows.push({
      sku,
      name: (cells[map.nama] ?? "").trim(),
      quantity: qty === null ? 0 : Math.round(qty),
      category: (cells[map.kategori] ?? "").trim() || null,
      unit: (cells[map.satuan] ?? "").trim() || null,
      purchase_price: NUM(cells[map.harga_beli]),
      selling_price: NUM(cells[map.harga_jual]),
      supplier_name: (cells[map.supplier] ?? "").trim() || null,
      location: (cells[map.lokasi] ?? "").trim() || null,
    });
  }
  return { rows, problems };
}

export default function ImportProducts() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [mode, setMode] = useState<ImportMode>("add");
  const [supplierId, setSupplierId] = useState("NONE");
  const [result, setResult] = useState<ProductImportResult | null>(null);

  const suppliersQ = useQuery({ queryKey: ["suppliers"], queryFn: () => apiGet<Supplier[]>("/suppliers") });
  const suppliers = suppliersQ.isError ? [] : suppliersQ.data ?? [];

  const { rows, problems } = useMemo(() => parseRows(text), [text]);
  const totalUnits = rows.reduce((s, r) => s + r.quantity, 0);

  const runImport = useMutation({
    mutationFn: (payload: ProductImportRequest) =>
      apiPost<ProductImportResult>("/products/import", payload),
    onSuccess: (res) => {
      void qc.invalidateQueries();
      setResult(res);
      toast.success(
        `Import selesai: ${res.created} produk baru, ${res.updated} diperbarui, ${angka(res.units_added)} unit masuk`,
      );
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
          ? (e.body as { detail: string }).detail
          : "Gagal mengimpor data";
      toast.error(msg);
    },
  });

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    const content = await file.text();
    setText(content);
    setResult(null);
    toast.success(`Berkas ${file.name} dibaca — periksa pratinjau sebelum menyimpan`);
  };

  const downloadTemplate = () => {
    const blob = new Blob([TEMPLATE], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "template-import-produk.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const submit = () => {
    if (rows.length === 0) {
      toast.error("Belum ada baris data yang bisa diimpor");
      return;
    }
    runImport.mutate({
      mode,
      supplier_id: supplierId === "NONE" ? null : supplierId,
      items: rows,
    });
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            Input Data Cepat
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
            Import Data SKU & Jumlah Stok
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Tempel data dari Excel atau unggah berkas CSV. Kolom minimal: <strong>SKU</strong>,{" "}
            <strong>Nama Barang</strong>, <strong>Jumlah</strong>. Satu supplier boleh menyuplai
            banyak barang — tulis nama supplier di kolom supplier atau pilih supplier bawaan.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <Card className="lg:col-span-7">
            <CardHeader>
              <CardTitle className="text-lg">1. Tempel atau Unggah Data</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={downloadTemplate} data-testid="btn-download-template">
                  <Download className="size-4" /> Unduh Template CSV
                </Button>
                <label
                  className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors duration-150 hover:bg-secondary"
                  data-testid="label-upload-csv"
                >
                  <FileUp className="size-4" /> Pilih Berkas CSV
                  <input
                    type="file"
                    accept=".csv,text/csv,text/plain"
                    className="hidden"
                    data-testid="input-import-file"
                    onChange={(e) => void onFile(e.target.files?.[0])}
                  />
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setText("");
                    setResult(null);
                  }}
                  data-testid="btn-clear-import"
                >
                  <Trash2 className="size-4" /> Bersihkan
                </Button>
              </div>

              <div className="space-y-2">
                <Label htmlFor="import-text">Data (CSV / tempel dari Excel)</Label>
                <Textarea
                  id="import-text"
                  rows={12}
                  className="font-mono text-xs"
                  placeholder={TEMPLATE}
                  data-testid="import-textarea"
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    setResult(null);
                  }}
                />
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Jika SKU sudah ada</Label>
                  <Select value={mode} onValueChange={(v: string) => setMode(v as ImportMode)}>
                    <SelectTrigger data-testid="import-mode-select">
                      <SelectValue>{(v) => MODE_LABELS[String(v)] ?? "Pilih mode"}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="add">Tambahkan ke stok yang ada</SelectItem>
                      <SelectItem value="replace">Ganti jumlah stok (timpa)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Supplier bawaan (opsional)</Label>
                  <Select value={supplierId} onValueChange={(v: string) => setSupplierId(v)}>
                    <SelectTrigger data-testid="import-supplier-select">
                      <SelectValue>
                        {(v) => suppliers.find((s) => s.id === v)?.name ?? "Tanpa supplier bawaan"}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="NONE">Tanpa supplier bawaan</SelectItem>
                      {suppliers.map((s) => (
                        <SelectItem key={s.id} value={s.id}>
                          {s.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <Button
                className="w-full"
                onClick={submit}
                disabled={runImport.isPending || rows.length === 0}
                data-testid="btn-submit-import"
              >
                <Upload className="size-4" />
                {runImport.isPending ? "Mengimpor..." : `Import ${angka(rows.length)} Baris Data`}
              </Button>
            </CardContent>
          </Card>

          <Card className="lg:col-span-5">
            <CardHeader>
              <CardTitle className="text-lg">2. Pratinjau</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2 text-sm">
                <Badge variant="secondary" data-testid="preview-row-count">
                  {angka(rows.length)} baris
                </Badge>
                <Badge variant="outline" data-testid="preview-unit-count">
                  {angka(totalUnits)} unit
                </Badge>
              </div>

              {problems.length > 0 && (
                <div className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
                  {problems.slice(0, 5).map((p) => (
                    <p key={p}>{p}</p>
                  ))}
                </div>
              )}

              {rows.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Belum ada data. Tempel isi spreadsheet atau unggah CSV untuk melihat pratinjau.
                </p>
              ) : (
                <div className="max-h-80 overflow-auto rounded-lg border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>SKU</TableHead>
                        <TableHead>Nama</TableHead>
                        <TableHead className="text-right">Jumlah</TableHead>
                        <TableHead className="text-right">Modal</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody data-testid="import-preview-body">
                      {rows.slice(0, 50).map((r, i) => (
                        <TableRow key={`${r.sku}-${i}`} data-testid="import-preview-row">
                          <TableCell className="font-mono text-xs">{r.sku}</TableCell>
                          <TableCell className="text-xs">{r.name || "—"}</TableCell>
                          <TableCell className="text-right font-mono text-xs">
                            {angka(r.quantity)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">
                            {r.purchase_price ? rupiah(r.purchase_price) : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {result && (
                <div
                  className="space-y-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-300"
                  data-testid="import-result"
                >
                  <p>{result.created} produk baru dibuat</p>
                  <p>{result.updated} produk diperbarui</p>
                  <p>{angka(result.units_added)} unit ditambahkan ke stok</p>
                  {result.suppliers_created > 0 && (
                    <p>{result.suppliers_created} supplier baru dibuat otomatis</p>
                  )}
                  {result.errors.length > 0 && (
                    <div className="mt-2 border-t border-emerald-500/20 pt-2 text-amber-300">
                      {result.errors.slice(0, 5).map((e) => (
                        <p key={e}>{e}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
