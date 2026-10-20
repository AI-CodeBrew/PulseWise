"use client";

import { useState } from "react";

import { Badge, Button, Message, useAction } from "@/components/ui/Form";
import { Async, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiPost } from "@/lib/api";
import { formatMoney, formatMonth, formatNumber, formatUsd, shiftMonth } from "@/lib/format";
import type { Currency, ExtraUsage, ExtraUsagePart } from "@/lib/types";

/**
 * What a client used ABOVE their plan, priced at PostHog's price plus your commission, with one button to invoice it.
 * Nothing is charged automatically: this is a suggestion for the admin. Clients never see this panel.
 */
export function ExtraUsagePanel({ clientId, currency, onChanged }: { clientId: string; currency: Currency; onChanged: () => void }) {
  const thisMonth = new Date().toISOString().slice(0, 7); // (UTC, like the usage counts)
  const lastMonth = shiftMonth(thisMonth, -1);
  const [month, setMonth] = useState(thisMonth);
  const info = useApi<ExtraUsage>(`/api/admin/clients/${clientId}/extra-usage`, { month });
  const create = useAction(async () => {
    await apiPost(`/api/admin/clients/${clientId}/extra-usage-invoice`, { month });
    info.reload();
    onChanged();
  });

  return (
    <div className="rounded-lg border border-line p-4" data-extra-usage>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">Extra usage</h3>
        <select
          aria-label="Month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          className="rounded-lg border border-line bg-page px-2 py-1 text-sm text-ink outline-none focus:border-accent"
        >
          <option value={thisMonth}>This month</option>
          <option value={lastMonth}>Last month ({formatMonth(lastMonth)})</option>
        </select>
      </div>
      <Async query={info} skeleton={<Skeleton className="mt-3 h-20" />}>
        {(x) => {
          if (!x.plan) return <p className="mt-2 text-sm text-ink-2">No plan, so nothing is &quot;above the plan&quot;.</p>;
          const parts: [string, ExtraUsagePart][] = [
            ["Events", x.events],
            ["Recordings", x.recordings],
          ];
          const over = parts.some(([, part]) => part.over > 0);
          if (!over) return <p className="mt-2 text-sm text-ink-2">Nothing above the {x.plan} plan in {formatMonth(x.month)}.</p>;
          return (
            <div className="mt-2 space-y-3">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="text-xs text-muted">
                      <th className="py-1 pr-3 font-medium"> </th>
                      <th className="py-1 pr-3 text-right font-medium">Used</th>
                      <th className="py-1 pr-3 text-right font-medium">In plan</th>
                      <th className="py-1 pr-3 text-right font-medium">Over</th>
                      <th className="py-1 pr-3 text-right font-medium">PostHog charges you</th>
                      <th className="py-1 text-right font-medium">You charge (+{x.commission_percent}%)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parts.map(([name, part]) => (
                      <tr key={name} className="border-t border-line tabular-nums">
                        <th className="py-1.5 pr-3 font-medium text-ink">{name}</th>
                        <td className="py-1.5 pr-3 text-right">{formatNumber(part.used)}</td>
                        <td className="py-1.5 pr-3 text-right">{part.included === null ? "No limit" : formatNumber(part.included)}</td>
                        <td className="py-1.5 pr-3 text-right">{formatNumber(part.over)}</td>
                        <td className="py-1.5 pr-3 text-right">{formatUsd(part.provider_usd)}</td>
                        <td className="py-1.5 text-right font-medium text-ink">{formatMoney(part.amount, currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {x.already_invoiced ? (
                <p className="text-sm text-ink-2" data-extra-invoiced>
                  <Badge tone={x.already_invoiced.status === "paid" ? "green" : "amber"}>{x.already_invoiced.status === "paid" ? "Paid" : "Invoiced"}</Badge> as {x.already_invoiced.number} (
                  {formatMoney(x.already_invoiced.amount, currency)}).
                </p>
              ) : x.can_invoice ? (
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="primary" busy={create.busy} onClick={() => create.run()}>
                    Create invoice for {formatMoney(x.amount, currency)}
                  </Button>
                  <span className="text-xs text-muted">Priced at PostHog&apos;s price for the extra amounts + your commission. Nothing is charged automatically.</span>
                </div>
              ) : (
                <p className="text-sm text-ink-2">Over the plan, but still inside PostHog&apos;s free allowance, so there is nothing to charge.</p>
              )}
              {create.error && <Message kind="error">{create.error}</Message>}
            </div>
          );
        }}
      </Async>
    </div>
  );
}
