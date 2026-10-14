"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { FullPageMessage } from "@/components/ui/FullPage";
import { useAuth } from "./AuthProvider";

/**
 * Shows `children` only to admins who are NOT currently viewing as a client.
 * (A convenience for the screen. The real protection is in the backend: every /api/admin/* call
 * is refused for anyone who isn't an admin.)
 */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  if (!me?.user.is_admin) {
    return (
      <FullPageMessage title="Admins only" linkHref="/" linkLabel="Go to my dashboard">
        This area is for the account administrators.
      </FullPageMessage>
    );
  }
  if (me.view_as) {
    return (
      <FullPageMessage title="You're viewing as a client">
        Exit the client view to use the admin tools.
        <div className="mt-4">
          <Link href={`/admin/clients/${me.view_as.client_id}`} className="text-accent hover:underline">
            Back to {me.view_as.client_name}
          </Link>
        </div>
      </FullPageMessage>
    );
  }
  return <>{children}</>;
}
