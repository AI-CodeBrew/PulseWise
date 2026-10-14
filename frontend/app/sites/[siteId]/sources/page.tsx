"use client";

import { useState } from "react";

import { HBarChart } from "@/components/charts/HBarChart";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useDays } from "@/hooks/useDays";
import { useSiteApi } from "@/hooks/useSite";
import { formatNumber } from "@/lib/format";
import type { SourceRow, Sources } from "@/lib/types";

const TABS = [
  { key: "channels", label: "Channels", hint: "Type of traffic: direct, search, social, referral…" },
  { key: "referrers", label: "Referring sites", hint: "The website a visitor came from" },
  { key: "utm_sources", label: "Campaigns (UTM)", hint: "From utm_source in your links" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function SourcesPage() {
  const api = useSiteApi();
  const days = useDays();
  const sources = useApi<Sources>(api("/sources"), { days });
  const [tab, setTab] = useState<TabKey>("channels");
  const current = TABS.find((t) => t.key === tab)!;

  return (
    <>
      <PageHeader title="Traffic sources" description="Where your visitors come from." />

      <Card>
        <CardHeader title="Visits by channel" />
        <Async query={sources} skeleton={<Skeleton className="mx-5 mb-5 h-40" />}>
          {(s) => (
            <HBarChart data={s.channels.map((c) => ({ name: c.name, value: c.sessions }))} valueLabel="Visits" />
          )}
        </Async>
      </Card>

      <Card className="mt-6">
        <div className="flex flex-wrap gap-1 px-4 pt-4 sm:px-5" role="tablist" aria-label="Source type">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={`rounded-md px-3 py-1.5 text-sm ${
                tab === t.key ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <p className="px-4 pb-3 pt-2 text-xs text-muted sm:px-5">{current.hint}</p>
        <Async query={sources} skeleton={<SkeletonRows />}>
          {(s) => <SourceTable rows={s[tab]} />}
        </Async>
      </Card>
    </>
  );
}

function SourceTable({ rows }: { rows: SourceRow[] }) {
  if (rows.length === 0) return <EmptyState message="Nothing here in this period." />;
  const total = rows.reduce((sum, r) => sum + r.sessions, 0);
  return (
    <DataTable
      rows={rows}
      rowKey={(r) => r.name}
      columns={[
        { header: "Source", cell: (r) => <span className="break-all">{r.name}</span> },
        { header: "Visits", align: "right", cell: (r) => formatNumber(r.sessions) },
        {
          header: "Share",
          align: "right",
          cell: (r) => (total ? `${((r.sessions / total) * 100).toFixed(1)}%` : "–"),
        },
        { header: "Visitors", align: "right", className: "hidden sm:table-cell", cell: (r) => formatNumber(r.visitors) },
      ]}
    />
  );
}
