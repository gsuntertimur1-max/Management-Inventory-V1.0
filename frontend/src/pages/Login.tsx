import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { LogIn, Warehouse } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Toaster } from "@/components/ui/sonner";
import { ApiError, apiPost } from "@/lib/api";
import { useAuth, useSession } from "@/lib/session";
import type { CurrentUser } from "@/lib/session";

export default function Login() {
  const navigate = useNavigate();
  const { beginSession } = useSession();
  const { user, isLoading } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (!isLoading && user) navigate("/", { replace: true });
  }, [isLoading, user, navigate]);

  const login = useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      apiPost<CurrentUser>("/auth/login", body),
    onSuccess: async (u) => {
      await beginSession();
      toast.success(`Selamat datang, ${u.full_name || u.username}`);
      navigate("/", { replace: true });
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && typeof (e.body as { detail?: string })?.detail === "string"
          ? (e.body as { detail: string }).detail
          : "Gagal masuk. Periksa koneksi.";
      toast.error(msg);
    },
  });

  const submit = () => {
    if (!username.trim() || !password) {
      toast.error("Username dan password wajib diisi");
      return;
    }
    login.mutate({ username: username.trim(), password });
  };

  return (
    <div className="relative grid min-h-screen place-items-center bg-background px-4">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-96 opacity-70"
        style={{
          background:
            "radial-gradient(60% 100% at 50% 0%, rgba(37,99,235,0.22) 0%, rgba(11,15,23,0) 70%)",
        }}
      />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/25">
            <Warehouse className="size-6" />
          </span>
          <div>
            <p className="text-lg font-bold tracking-tight">GudangPro</p>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Sistem Manajemen Stok
            </p>
          </div>
        </div>

        <Card>
          <CardContent className="space-y-5">
            <div>
              <h1 className="text-xl font-bold tracking-tight">Masuk ke Akun Anda</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Gunakan akun yang diberikan administrator gudang.
              </p>
            </div>

            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  autoComplete="username"
                  placeholder="admin"
                  data-testid="login-username-input"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="••••••••"
                  data-testid="login-password-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              <Button
                type="submit"
                className="w-full"
                disabled={login.isPending}
                data-testid="login-submit-button"
              >
                <LogIn className="size-4" />
                {login.isPending ? "Memproses..." : "Masuk"}
              </Button>
            </form>

            <p className="rounded-lg border border-border bg-secondary/40 p-3 text-xs text-muted-foreground">
              Akun administrator bawaan: <span className="font-mono text-foreground">admin</span> /{" "}
              <span className="font-mono text-foreground">admin123</span> — segera ganti password di
              halaman Pengguna.
            </p>
          </CardContent>
        </Card>
      </div>
      <Toaster position="top-right" richColors />
    </div>
  );
}
