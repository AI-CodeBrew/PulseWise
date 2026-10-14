"use client";

import { useState } from "react";

import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { SelectField } from "@/components/ui/Form";
import { LoadMore, PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useCursorList } from "@/hooks/useCursorList";
import { auditLabel, auditSummary } from "@/lib/audit";
import { formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";

const FILTERS = [
  { value: "", label: "Everything" },
  { value: "admin.", label: "Admin actions" },
  { value: "auth.login", label: "Logins" },
  { value: "auth.", label: "Passwords and logins" },
];

export default function AuditPage() {
  const [filter, setFilter] = useState("");
  const list = useCursorList<AuditEntry>("/api/admin/audit", { limit: 50, action: filter || undefined });

  return (
    <>
      <PageHeader title="Audit log" description="Who did what, and when. Passwords and keys are never recorded here." />
      <div className="mb-4 max-w-xs">
        <SelectField label="Show" value={filter} onChange={(e) => setFilter(e.target.value)}>
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </SelectField>
      </div>
      <Card className="pt-1">
        <Async query={list} skeleton={<div className="pt-4"><SkeletonRows rows={10} /></div>}>
          {() =>
            list.items.length === 0 ? (
              <EmptyState message="Nothing recorded yet." />
            ) : (
              <>
                <DataTable
                  rows={list.items}
                  rowKey={(e) => e.id}
                  columns={[
                    { header: "When", cell: (e) => <span className="whitespace-nowrap">{e.created_at ? formatDateTime(e.created_at) : ""}</span> },
                    { header: "Who", cell: (e) => e.actor ?? <span className="text-muted">system / unknown</span> },
                    {
                      header: "What",
                      cell: (e) => (
                        <div>
                          <span className="font-medium">{auditLabel(e.action)}</span>
                          {e.details && <span className="block break-words text-xs text-muted">{auditSummary(e.details)}</span>}
                        </div>
                      ),
                    },
                    { header: "From", className: "hidden md:table-cell", cell: (e) => <span className="font-mono text-xs">{e.ip ?? "–"}</span> },
                  ]}
                />
                <LoadMore hasMore={list.hasMore} loading={list.loadingMore} error={list.moreError} onClick={list.loadMore} />
              </>
            )
          }
        </Async>
      </Card>
    </>
  );
}
