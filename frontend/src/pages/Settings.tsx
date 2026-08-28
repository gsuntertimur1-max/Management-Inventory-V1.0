import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPut } from "@/lib/api";
import type { AppSettings } from "@/lib/types";

const FALLBACK: AppSettings = {
  company_name: "Bulog Gudang Sunter Timur I & II",
  address: "",
  phone: "",
  email: "",
  footer_note: "",
};

export default function Settings() {
  const qc = useQueryClient();
  const [form, setForm] = useState<AppSettings>(FALLBACK);

  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<AppSettings>("/settings") });

  useEffect(() => {
    if (settingsQ.data) setForm(settingsQ.data);
  }, [settingsQ.data]);

  const save = useMutation({
    mutationFn: (payload: AppSettings) => apiPut<AppSettings>("/settings", payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Kop surat & data perusahaan diperbarui");
    },
    onError: () => toast.error("Gagal menyimpan pengaturan"),
  });

  return (
    <AppShell>
      <div className="animate-rise max-w-3xl space-y-6">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Konfigurasi</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Pengaturan Perusahaan</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Data ini dipakai sebagai kop pada surat jalan A4 dan bon muat thermal 80mm.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Identitas & Kop Cetak</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="c-name">Nama Perusahaan</Label>
              <Input
                id="c-name"
                data-testid="form-settings-company-name"
                value={form.company_name}
                onChange={(e) => setForm({ ...form, company_name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="c-addr">Alamat</Label>
              <Textarea
                id="c-addr"
                rows={2}
                data-testid="form-settings-address"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="c-phone">Telepon</Label>
                <Input
                  id="c-phone"
                  data-testid="form-settings-phone"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="c-email">Email</Label>
                <Input
                  id="c-email"
                  data-testid="form-settings-email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="c-footer">Catatan Kaki Surat Jalan</Label>
              <Textarea
                id="c-footer"
                rows={2}
                data-testid="form-settings-footer"
                value={form.footer_note}
                onChange={(e) => setForm({ ...form, footer_note: e.target.value })}
              />
            </div>
            <Button
              onClick={() => save.mutate(form)}
              disabled={save.isPending}
              data-testid="btn-save-settings"
            >
              <Save className="size-4" />
              {save.isPending ? "Menyimpan..." : "Simpan Pengaturan"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
