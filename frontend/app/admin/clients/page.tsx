"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, TextField } from "@/components/ui/Form";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import type { AdminClient, ListResponse } from "@/lib/types";

export default function ClientsPage() {
  const [search, setSearch] = useState("");
  const clients = useApi<ListResponse<AdminClient>>("/api/admin/clients", { q: search.trim() || undefined });

  return (
    <>
      <PageHeader
        title="Clients"
        description="The businesses you serve. Each has its own websites and people."
        action={
          <Link href="/admin/clients/new" className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90">
            + New client
          </Link>
        }
      />
      <div className="mb-4 max-w-xs">
        <TextField label="Search" placeholder="Client name…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <Card className="pt-1">
        <Async query={clients} skeleton={<div className="pt-4"><SkeletonRows rows={6} /></div>}>
          {(c) =>
            c.results.length === 0 ? (
              <EmptyState message={search ? "No client matches that name." : "No clients yet. Create your first one."} />
            ) : (
              <DataTable
                rows={c.results}
                rowKey={(r) => r.id}
                rowHref={(r) => `/admin/clients/${r.id}`}
                columns={[
                  { header: "Client", cell: (r) => <span className="font-medium">{r.name}</span> },
                  {
                    header: "Status",
                    cell: (r) => (r.status === "active" ? <Badge tone="green">Active</Badge> : <Badge tone="red">Suspended</Badge>),
                  },
                  { header: "Websites", align: "right", cell: (r) => r.websites },
                  { header: "People", align: "right", className: "hidden sm:table-cell", cell: (r) => r.members },
                  { header: "Contact", className: "hidden md:table-cell", cell: (r) => r.contact_email ?? "–" },
                ]}
              />
            )
          }
        </Async>
      </Card>
    </>
  );
}
