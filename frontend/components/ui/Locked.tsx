"use client";

import { useAuth } from "@/components/auth/AuthProvider";
import { SupportLinks } from "@/components/billing/parts";
import { Card } from "@/components/ui/Card";

/** Shown instead of a page when the client's plan doesn't include it (the server answers 403). */
export function LockedState({ message }: { message: string }) {
  const { me } = useAuth();
  return (
    <Card className="p-6 text-center">
      <h2 className="text-base font-semibold text-ink">Not part of your plan</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">{message}</p>
      <SupportLinks support={me?.support} className="mt-4 justify-center" />
    </Card>
  );
}
