"use client";

import { AdminShell } from "@/components/admin/AdminShell";
import { RequireAdmin } from "@/components/auth/RequireAdmin";
import { RequireAuth } from "@/components/auth/RequireAuth";

/** Every /admin page: must be logged in AND be an admin (the backend enforces it again on every call). */
export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <RequireAuth>
      <RequireAdmin>
        <AdminShell>{children}</AdminShell>
      </RequireAdmin>
    </RequireAuth>
  );
}
