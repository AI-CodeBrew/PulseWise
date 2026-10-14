"use client";

import { HBarChart } from "@/components/charts/HBarChart";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useDays } from "@/hooks/useDays";
import { useSiteApi } from "@/hooks/useSite";
import { formatNumber } from "@/lib/format";
import type { BreakdownRow, Devices, Geo } from "@/lib/types";

export default function AudiencePage() {
  const api = useSiteApi();
  const days = useDays();
  const geo = useApi<Geo>(api("/geo"), { days });
  const devices = useApi<Devices>(api("/devices"), { days });

  const toBars = (rows: BreakdownRow[]) => rows.map((r) => ({ name: r.name, value: r.visitors }));

  return (
    <>
      <PageHeader title="Audience" description="Where your visitors are, and what they use." />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Countries" />
          <Async query={geo} skeleton={<SkeletonRows />}>
            {(g) =>
              g.countries.length === 0 ? (
                <EmptyState message="No visitors in this period." />
              ) : (
                <DataTable
                  rows={g.countries}
                  rowKey={(r) => `${r.code}-${r.country}`}
                  columns={[
                    {
                      header: "Country",
                      cell: (r) => (
                        <span>
                          {r.code && (
                            <span className="mr-2 inline-block w-7 rounded bg-surface-2 text-center text-[10px] font-semibold text-ink-2">
                              {r.code}
                            </span>
                          )}
                          {r.country}
                        </span>
                      ),
                    },
                    { header: "Visitors", align: "right", cell: (r) => formatNumber(r.visitors) },
                    { header: "Views", align: "right", cell: (r) => formatNumber(r.views) },
                  ]}
                />
              )
            }
          </Async>
        </Card>

        <Card>
          <CardHeader title="Cities" />
          <Async query={geo} skeleton={<SkeletonRows />}>
            {(g) =>
              g.cities.length === 0 ? (
                <EmptyState message="No visitors in this period." />
              ) : (
                <DataTable
                  rows={g.cities}
                  rowKey={(r) => `${r.city}-${r.country}`}
                  columns={[
                    {
                      header: "City",
                      cell: (r) => (
                        <span>
                          {r.city} <span className="text-muted">· {r.country}</span>
                        </span>
                      ),
                    },
                    { header: "Visitors", align: "right", cell: (r) => formatNumber(r.visitors) },
                    { header: "Views", align: "right", cell: (r) => formatNumber(r.views) },
                  ]}
                />
              )
            }
          </Async>
        </Card>
      </div>

      <h2 className="mb-3 mt-8 text-sm font-semibold text-ink">Devices</h2>
      <div className="grid gap-6 lg:grid-cols-3">
        {(
          [
            ["device_types", "Device type"],
            ["browsers", "Browser"],
            ["operating_systems", "Operating system"],
          ] as const
        ).map(([key, title]) => (
          <Card key={key}>
            <CardHeader title={title} subtitle="Visitors" />
            <Async query={devices} skeleton={<Skeleton className="mx-5 mb-5 h-32" />}>
              {(d) => <HBarChart data={toBars(d[key])} valueLabel="Visitors" maxRows={6} />}
            </Async>
          </Card>
        ))}
      </div>
    </>
  );
}
