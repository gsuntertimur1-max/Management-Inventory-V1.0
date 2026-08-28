import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Pencil, Phone, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { angka } from "@/lib/format";
import type { Product, Supplier, SupplierCreate } from "@/lib/types";

const EMPTY: SupplierCreate = {
  name: "",
  contact_person: "",
  phone: "",
  email: "",
  address: "",
  category_supplied: "",
};

export default function Suppliers() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<SupplierCreate>(EMPTY);

  const suppliersQ = useQuery({ queryKey: ["suppliers"], queryFn: () => apiGet<Supplier[]>("/suppliers") });
  const productsQ = useQuery({ queryKey: ["products"], queryFn: () => apiGet<Product[]>("/products") });

  const suppliers = suppliersQ.isError ? [] : suppliersQ.data ?? [];
  const products = productsQ.isError ? [] : productsQ.data ?? [];

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const p of products) {
      if (p.supplier_id) map[p.supplier_id] = (map[p.supplier_id] ?? 0) + 1;
    }
    return map;
  }, [products]);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["suppliers"] });
    void qc.invalidateQueries({ queryKey: ["products"] });
  };

  const save = useMutation({
    mutationFn: (payload: SupplierCreate) =>
      editingId
        ? apiPut<Supplier>(`/suppliers/${editingId}`, payload)
        : apiPost<Supplier>("/suppliers", payload),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      toast.success(editingId ? "Data supplier diperbarui" : "Supplier baru ditambahkan");
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
          ? (e.body as { detail: string }).detail
          : "Gagal menyimpan supplier";
      toast.error(msg);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`/suppliers/${id}`),
    onSuccess: () => {
      invalidate();
      toast.success("Supplier dihapus");
    },
    onError: () => toast.error("Gagal menghapus supplier"),
  });

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY);
    setOpen(true);
  };

  const openEdit = (s: Supplier) => {
    setEditingId(s.id);
    setForm({
      name: s.name,
      contact_person: s.contact_person,
      phone: s.phone,
      email: s.email,
      address: s.address,
      category_supplied: s.category_supplied,
    });
    setOpen(true);
  };

  const submit = () => {
    if (!form.name.trim() || !form.phone.trim()) {
      toast.error("Nama supplier dan nomor telepon wajib diisi");
      return;
    }
    save.mutate(form);
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Mitra Pasokan</p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Daftar Supplier & Vendor</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {angka(suppliers.length)} supplier terdaftar
            </p>
          </div>
          <Button onClick={openCreate} data-testid="btn-create-supplier">
            <Plus className="size-4" /> Tambah Supplier
          </Button>
        </div>

        <div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
          data-testid="table-suppliers-body"
        >
          {suppliers.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Belum ada supplier. Tambah supplier atau muat data contoh.
            </p>
          )}
          {suppliers.map((s) => (
            <Card
              key={s.id}
              data-testid="supplier-card"
              className="transition-transform duration-150 hover:-translate-y-0.5"
            >
              <CardContent className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold">{s.name}</p>
                    <p className="text-xs text-muted-foreground">
                      PIC: {s.contact_person || "—"}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Edit ${s.name}`}
                      data-testid="btn-edit-supplier"
                      onClick={() => openEdit(s)}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Hapus ${s.name}`}
                      data-testid="btn-delete-supplier"
                      onClick={() => remove.mutate(s.id)}
                    >
                      <Trash2 className="size-4 text-red-400" />
                    </Button>
                  </div>
                </div>
                {s.category_supplied && <Badge variant="secondary">{s.category_supplied}</Badge>}
                <div className="space-y-1.5 text-xs text-muted-foreground">
                  <p className="flex items-center gap-2">
                    <Phone className="size-3.5" /> {s.phone}
                  </p>
                  <p className="flex items-center gap-2 truncate">
                    <Mail className="size-3.5" /> {s.email || "—"}
                  </p>
                  <p className="line-clamp-2">{s.address || "—"}</p>
                </div>
                <p className="border-t border-border pt-2 font-mono text-xs">
                  {angka(counts[s.id] ?? 0)} produk disuplai
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingId ? "Ubah Supplier" : "Tambah Supplier Baru"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="s-name">Nama Perusahaan / Supplier</Label>
              <Input
                id="s-name"
                data-testid="form-supplier-name"
                placeholder="PT Mega Nusantara Distribusi"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="s-pic">Nama Kontak PIC</Label>
                <Input
                  id="s-pic"
                  data-testid="form-supplier-contact"
                  value={form.contact_person}
                  onChange={(e) => setForm({ ...form, contact_person: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="s-phone">Telepon / WhatsApp</Label>
                <Input
                  id="s-phone"
                  data-testid="form-supplier-phone"
                  placeholder="0812-3456-7890"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="s-email">Alamat Email</Label>
              <Input
                id="s-email"
                data-testid="form-supplier-email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="s-addr">Alamat Kantor / Gudang</Label>
              <Input
                id="s-addr"
                data-testid="form-supplier-address"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="s-cat">Kategori Pasokan Utama</Label>
              <Input
                id="s-cat"
                data-testid="form-supplier-category"
                value={form.category_supplied}
                onChange={(e) => setForm({ ...form, category_supplied: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} data-testid="btn-cancel-supplier">
              Batal
            </Button>
            <Button onClick={submit} disabled={save.isPending} data-testid="btn-submit-supplier">
              {save.isPending ? "Menyimpan..." : "Simpan Supplier"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
