import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { apiPost } from "@/lib/api";
import type { CurrentUser } from "@/lib/session";

/**
 * Menukar session_id dari Emergent Google Auth (ada di URL fragment) menjadi sesi aplikasi.
 * REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
 */
export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const processed = useRef(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const sessionId = new URLSearchParams(location.hash.replace(/^#/, "")).get("session_id");
    if (!sessionId) {
      navigate("/login", { replace: true });
      return;
    }

    (async () => {
      try {
        await apiPost<CurrentUser>("/auth/google/session", { session_id: sessionId });
        window.history.replaceState(null, "", window.location.pathname);
        qc.clear();
        await qc.invalidateQueries();
        navigate("/", { replace: true });
      } catch {
        setError("Login Google gagal. Silakan coba lagi.");
        window.history.replaceState(null, "", window.location.pathname);
        setTimeout(() => navigate("/login", { replace: true }), 1800);
      }
    })();
  }, [location.hash, navigate, qc]);

  return (
    <div className="grid min-h-screen place-items-center bg-background" data-testid="auth-callback">
      <div className="flex flex-col items-center gap-3 text-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground" data-testid="auth-callback-status">
          {error || "Menyiapkan sesi Anda..."}
        </p>
      </div>
    </div>
  );
}
