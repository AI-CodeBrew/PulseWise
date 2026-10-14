"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/AuthProvider";
import { Button, useAction } from "@/components/ui/Form";
import { apiPost } from "@/lib/api";
import type { Me } from "@/lib/types";

/** Shown at the very top while an admin looks at the dashboard exactly as a client sees it. */
export function ViewAsBanner() {
  const { me, setMe } = useAuth();
  const router = useRouter();
  const exit = useAction(async () => {
    const clientId = me?.view_as?.client_id;
    const updated = await apiPost<Me>("/api/auth/view-as/end");
    setMe(updated);
    router.push(clientId ? `/admin/clients/${clientId}` : "/admin");
  });

  if (!me?.view_as) return null;
  return (
    <div role="status" className="sticky top-0 z-50 flex flex-wrap items-center justify-center gap-3 bg-ink px-4 py-2 text-sm text-page">
      <span>
        <strong>Viewing as {me.view_as.client_name}</strong> · read-only · this is exactly what they see
      </span>
      <Button variant="secondary" busy={exit.busy} onClick={() => exit.run()} className="!py-1 text-xs">
        Exit client view
      </Button>
    </div>
  );
}
