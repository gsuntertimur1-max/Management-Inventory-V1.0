import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, Trash2, UserCog } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { waktu } from "@/lib/format";
import { ROLE_HINTS, ROLE_LABELS, useAuth } from "@/lib/session";
import type { CurrentUser, Role } from "@/lib/session";

const ROLE_VARIANT: Record<Role, "default" | "secondary" | "outline"> = {
  admin: "default",
  penjualan: "secondary",
  pengadaan: "secondary",
  viewer: "outline",
};

const ROLE_OPTIONS: Role[] = ["admin", "penjualan", "pengadaan", "viewer"];

export default function Users() {
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [password, setPassword] = useState("");
  const [pwTarget, setPwTarget] = useState<CurrentUser | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const usersQ = useQuery({ queryKey: ["users"], queryFn: () => apiGet<CurrentUser[]>("/auth/users") });
  const users = usersQ.isError ? [] : usersQ.data ?? [];

  const errMsg = (e: unknown, fallback: string) =>
    e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
      ? (e.body as { detail: string }).detail
      : fallback;

  const invalidate = () => void qc.invalidateQueries({ queryKey: ["users"] });

  const create = useMutation({
    mutationFn: (body: { username: string; full_name: string; role: Role; password: string }) =>
      apiPost<CurrentUser>("/auth/users", body),
    onSuccess: (u) => {
      invalidate();
      setOpen(false);
      setUsername("");
      setFullName("");
      setPassword("");
      setRole("viewer");
      toast.success(`Akun ${u.username} dibuat sebagai ${ROLE_LABELS[u.role]}`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal membuat akun")),
  });

  const changeRole = useMutation({
    mutationFn: (vars: { id: string; role: Role }) =>
      apiPatch<CurrentUser>(`/auth/users/${vars.id}`, { role: vars.role }),
    onSuccess: (u) => {
      invalidate();
      toast.success(`Peran ${u.username} diubah menjadi ${ROLE_LABELS[u.role]}`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal mengubah peran")),
  });

  const changePassword = useMutation({
    mutationFn: (vars: { id: string; password: string }) =>
      apiPatch<CurrentUser>(`/auth/users/${vars.id}`, { password: vars.password }),
    onSuccess: (u) => {
      invalidate();
      setPwTarget(null);
      setNewPassword("");
      toast.success(`Password ${u.username} diperbarui`);
    },
    onError: (e) => toast.error(errMsg(e, "Gagal mengubah password")),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`/auth/users/${id}`),
    onSuccess: () => {
      invalidate();
      toast.success("Akun dihapus");
    },
    onError: (e) => toast.error(errMsg(e, "Gagal menghapus akun")),
  });

  const submit = () => {
    if (username.trim().length < 3) {
      toast.error("Username minimal 3 karakter");
      return;
    }
    if (password.length < 6) {
      toast.error("Password minimal 6 karakter");
      return;
    }
    create.mutate({ username: username.trim(), full_name: fullName.trim(), role, password });
  };

  return (
    <AppShell>
      <div className="animate-rise space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Kontrol Akses
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Pengguna & Peran</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Admin mengatur semuanya, Operator mencatat stok & surat jalan, Pemantau hanya melihat
              sisa stok.
            </p>
          </div>
          <Button onClick={() => setOpen(true)} data-testid="btn-create-user">
            <Plus className="size-4" /> Tambah Akun
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ROLE_OPTIONS.map((r) => (
            <Card key={r} data-testid={`role-card-${r}`}>
              <CardContent className="space-y-2">
                <Badge variant={ROLE_VARIANT[r]}>{ROLE_LABELS[r]}</Badge>
                <p className="text-xs text-muted-foreground">{ROLE_HINTS[r]}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card className="overflow-hidden p-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Username</TableHead>
                  <TableHead>Nama Lengkap</TableHead>
                  <TableHead>Peran</TableHead>
                  <TableHead>Dibuat</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="table-users-body">
                {users.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-10 text-center text-sm text-muted-foreground">
                      Belum ada akun terdaftar.
                    </TableCell>
                  </TableRow>
                )}
                {users.map((u) => (
                  <TableRow key={u.id} data-testid={`user-row-${u.username}`}>
                    <TableCell className="font-mono text-sm font-semibold">
                      {u.username}
                      {me?.id === u.id && (
                        <span className="ml-2 text-xs text-muted-foreground">(Anda)</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm">{u.full_name || "—"}</TableCell>
                    <TableCell>
                      <Select
                        value={u.role}
                        onValueChange={(v: string) => changeRole.mutate({ id: u.id, role: v as Role })}
                      >
                        <SelectTrigger className="w-48" data-testid={`user-role-select-${u.username}`}>
                          <SelectValue>{(v) => ROLE_LABELS[v as Role] ?? String(v)}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTIONS.map((r) => (
                            <SelectItem key={r} value={r}>
                              {ROLE_LABELS[r]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{waktu(u.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Ubah password ${u.username}`}
                          data-testid={`btn-change-password-${u.username}`}
                          onClick={() => {
                            setPwTarget(u);
                            setNewPassword("");
                          }}
                        >
                          <KeyRound className="size-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Hapus ${u.username}`}
                          data-testid={`btn-delete-user-${u.username}`}
                          onClick={() => remove.mutate(u.id)}
                        >
                          <Trash2 className="size-4 text-red-400" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Tambah Akun Baru</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="u-name">Username</Label>
              <Input
                id="u-name"
                placeholder="operator1"
                data-testid="form-user-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="u-full">Nama Lengkap</Label>
              <Input
                id="u-full"
                placeholder="Budi Petugas Gudang"
                data-testid="form-user-fullname"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Peran</Label>
              <Select value={role} onValueChange={(v: string) => setRole(v as Role)}>
                <SelectTrigger data-testid="form-user-role">
                  <SelectValue>{(v) => ROLE_LABELS[v as Role] ?? "Pilih peran"}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((r) => (
                    <SelectItem key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{ROLE_HINTS[role]}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="u-pass">Password (min. 6 karakter)</Label>
              <Input
                id="u-pass"
                type="password"
                data-testid="form-user-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} data-testid="btn-cancel-user">
              Batal
            </Button>
            <Button onClick={submit} disabled={create.isPending} data-testid="btn-submit-user">
              <UserCog className="size-4" />
              {create.isPending ? "Menyimpan..." : "Simpan Akun"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!pwTarget} onOpenChange={(v) => !v && setPwTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Ubah Password {pwTarget?.username}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="u-newpass">Password Baru</Label>
            <Input
              id="u-newpass"
              type="password"
              data-testid="form-new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Sesi aktif akun ini akan berakhir setelah password diganti.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPwTarget(null)} data-testid="btn-cancel-password">
              Batal
            </Button>
            <Button
              disabled={changePassword.isPending}
              data-testid="btn-submit-password"
              onClick={() => {
                if (newPassword.length < 6) {
                  toast.error("Password minimal 6 karakter");
                  return;
                }
                if (pwTarget) changePassword.mutate({ id: pwTarget.id, password: newPassword });
              }}
            >
              Simpan Password
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
