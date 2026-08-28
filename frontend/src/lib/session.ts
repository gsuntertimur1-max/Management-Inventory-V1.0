import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export type Role = "admin" | "penjualan" | "pengadaan" | "viewer";

export interface CurrentUser {
  id: string;
  username: string;
  full_name: string;
  role: Role;
  email: string;
  picture: string;
  auth_provider: "password" | "google";
  created_at: string;
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  penjualan: "Penjualan",
  pengadaan: "Pengadaan",
  viewer: "Pemantau Stok",
};

export const ROLE_HINTS: Record<Role, string> = {
  admin: "Akses penuh: semua data, pengaturan & pengguna",
  penjualan: "Hanya pengeluaran barang & surat jalan",
  pengadaan: "Hanya pengadaan: PO, stok masuk, produk & supplier",
  viewer: "Hanya melihat sisa stok & penjualan (tanpa harga)",
};

const PERMISSIONS: Record<Role, string[]> = {
  admin: [
    "stock:read",
    "sales:read",
    "sales:write",
    "procurement:read",
    "procurement:write",
    "inventory:read",
    "reports:read",
    "settings:write",
    "users:manage",
    "data:reset",
  ],
  penjualan: ["stock:read", "sales:read", "sales:write", "inventory:read", "reports:read"],
  pengadaan: [
    "stock:read",
    "procurement:read",
    "procurement:write",
    "inventory:read",
    "reports:read",
  ],
  viewer: ["stock:read", "sales:read"],
};

/** Server is the source of truth; this only shapes the UI. `a|b` means "either action". */
export const can = (role: Role | undefined, action: string): boolean =>
  !!role && action.split("|").some((a) => PERMISSIONS[role].includes(a.trim()));

export function useAuth() {
  const query = useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<CurrentUser | null>("/auth/me"),
    retry: false,
    staleTime: 30_000,
  });

  return {
    user: query.data ?? null,
    role: query.data?.role,
    isLoading: query.isLoading,
    isLoggedIn: !!query.data,
  };
}

export function useSession() {
  const qc = useQueryClient();
  return {
    // Clearing the cache on both ends stops one account's data showing for the next login.
    beginSession: async () => {
      qc.clear();
      await qc.invalidateQueries();
    },
    endSession: async () => {
      await apiPost<{ ok: boolean }>("/auth/logout");
      qc.clear();
    },
  };
}
