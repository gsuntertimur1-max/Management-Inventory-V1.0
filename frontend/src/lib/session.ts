import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";

export type Role = "admin" | "operator" | "viewer";

export interface CurrentUser {
  id: string;
  username: string;
  full_name: string;
  role: Role;
  created_at: string;
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  operator: "Operator Gudang",
  viewer: "Pemantau Stok",
};

const PERMISSIONS: Record<Role, string[]> = {
  admin: [
    "stock:read",
    "inventory:read",
    "inventory:write",
    "reports:read",
    "settings:write",
    "users:manage",
    "data:reset",
  ],
  operator: ["stock:read", "inventory:read", "inventory:write", "reports:read"],
  viewer: ["stock:read"],
};

/** Server is the source of truth; this only shapes the UI. */
export const can = (role: Role | undefined, action: string): boolean =>
  !!role && PERMISSIONS[role].includes(action);

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
