import { Navigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { can, useAuth } from "@/lib/session";

/** Route gate. The server enforces the real policy; this keeps the UI coherent. */
export default function RequireAuth({
  action,
  children,
}: {
  action: string;
  children: React.ReactNode;
}) {
  const { user, role, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-background" data-testid="auth-loading">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (!can(role, action)) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
