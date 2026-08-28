import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, LogIn } from "lucide-react";
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
  const [showPassword, setShowPassword] = useState(false);

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
          <img
            src="/logo-bulog.png"
            alt="Logo Bulog Gudang Sunter Timur I & II"
            className="h-12 w-auto rounded-xl bg-white/95 p-1.5 object-contain"
          />
          <div>
            <p className="text-lg font-bold tracking-tight">Bulog Gudang Sunter Timur I &amp; II</p>
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
                {/* Mobile keyboards auto-capitalise by default, which silently breaks login. */}
                <Input
                  id="username"
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  placeholder="admin"
                  data-testid="login-username-input"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    className="pr-10"
                    placeholder="••••••••"
                    data-testid="login-password-input"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    aria-label={showPassword ? "Sembunyikan password" : "Tampilkan password"}
                    data-testid="login-toggle-password"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors duration-150 hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Password peka huruf besar/kecil. Ketuk ikon mata untuk memeriksa ketikan Anda.
                </p>
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

            <div className="flex items-center gap-3">
              <span className="h-px flex-1 bg-border" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                atau
              </span>
              <span className="h-px flex-1 bg-border" />
            </div>

            {/* REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH */}
            <Button
              type="button"
              variant="outline"
              className="w-full"
              data-testid="login-google-button"
              onClick={() => {
                const redirectUrl = window.location.origin + "/";
                window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
              }}
            >
              <svg className="size-4" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fill="#4285F4"
                  d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.54 5.54 0 0 1-2.4 3.63v3h3.86c2.26-2.09 3.56-5.17 3.56-8.87z"
                />
                <path
                  fill="#34A853"
                  d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09A11.99 11.99 0 0 0 12 24z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.27 14.29a7.2 7.2 0 0 1 0-4.58V6.62H1.29a12 12 0 0 0 0 10.76l3.98-3.09z"
                />
                <path
                  fill="#EA4335"
                  d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.69 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z"
                />
              </svg>
              Masuk dengan Google
            </Button>

            <p className="rounded-lg border border-border bg-secondary/40 p-3 text-xs text-muted-foreground">
              Akun administrator bawaan: <span className="font-mono text-foreground">admin</span> /{" "}
              <span className="font-mono text-foreground">admin123</span> — segera ganti password di
              halaman Pengguna. Akun Google baru selain pemilik aplikasi masuk sebagai{" "}
              <span className="text-foreground">Pemantau</span> sampai admin menaikkan perannya.
            </p>
          </CardContent>
        </Card>
      </div>
      <Toaster position="top-right" richColors />
    </div>
  );
}
