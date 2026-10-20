"use client";

import Link from "next/link";
import { useState } from "react";

import { EditLoginPanel } from "@/components/admin/EditLoginPanel";
import { useAuth } from "@/components/auth/AuthProvider";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Badge, Button, CodeBlock, Message, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiPatch, apiPost } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AdminUser, ListResponse } from "@/lib/types";

export default function UsersPage() {
  const { me } = useAuth();
  const [search, setSearch] = useState("");
  const users = useApi<ListResponse<AdminUser>>("/api/admin/users", { q: search.trim() || undefined });
  const [link, setLink] = useState<{ email: string; url: string } | null>(null);
  const [loginFor, setLoginFor] = useState<{ id: string; email: string } | null>(null);

  const action = useAction(async (run: () => Promise<unknown>) => {
    await run();
    users.reload();
  });

  return (
    <>
      <PageHeader
        title="Users"
        description="Everyone who can log in."
        action={
          <Link href="/admin/users/new" className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90">
            + Add user
          </Link>
        }
      />
      <div className="mb-4 max-w-xs">
        <TextField label="Search" placeholder="Name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      {action.error && (
        <div className="mb-4">
          <Message kind="error">{action.error}</Message>
        </div>
      )}
      {link && (
        <div className="mb-4 space-y-2">
          <Message kind="success">New invitation link for {link.email} (works once, for 7 days):</Message>
          <CodeBlock code={link.url} label="Invitation link" />
        </div>
      )}
      {loginFor && (
        <div className="mb-4">
          <EditLoginPanel key={loginFor.id} userId={loginFor.id} email={loginFor.email} onClose={() => setLoginFor(null)} onSaved={users.reload} />
        </div>
      )}
      <Card className="pt-1">
        <Async query={users} skeleton={<div className="pt-4"><SkeletonRows rows={6} /></div>}>
          {(u) =>
            u.results.length === 0 ? (
              <EmptyState message="No users found." />
            ) : (
              <DataTable
                rows={u.results}
                rowKey={(r) => r.id}
                columns={[
                  {
                    header: "Person",
                    cell: (r) => (
                      <div>
                        <span className="font-medium">{r.name || r.email}</span>
                        {r.name && <span className="block text-xs text-muted">{r.email}</span>}
                      </div>
                    ),
                  },
                  {
                    header: "Access",
                    cell: (r) =>
                      r.is_admin ? (
                        <Badge tone="blue">Admin</Badge>
                      ) : r.clients.length === 0 ? (
                        <span className="text-muted">none</span>
                      ) : (
                        <div className="space-y-0.5 text-sm">
                          {r.clients.map((c) => (
                            <div key={c.id}>
                              <Link href={`/admin/clients/${c.id}`} className="hover:text-accent hover:underline">
                                {c.name}
                              </Link>{" "}
                              <span className="text-xs text-muted">({c.role})</span>
                            </div>
                          ))}
                        </div>
                      ),
                  },
                  { header: "Last login", className: "hidden sm:table-cell", cell: (r) => (r.last_login_at ? formatDateTime(r.last_login_at) : "never") },
                  { header: "Status", cell: (r) => (r.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Deactivated</Badge>) },
                  {
                    header: "",
                    align: "right",
                    cell: (r) => (
                      <div className="flex flex-wrap justify-end gap-2">
                        {!r.is_admin && (
                          <>
                            <Button
                              variant="ghost"
                              className="!px-2 !py-1 text-xs"
                              onClick={() => {
                                setLink(null);
                                setLoginFor({ id: r.id, email: r.email });
                              }}
                            >
                              Edit login
                            </Button>
                            <Button
                              variant="ghost"
                              className="!px-2 !py-1 text-xs"
                              onClick={() =>
                                action.run(async () => {
                                  const result = await apiPost<{ email: string; invite_link: string }>(`/api/admin/users/${r.id}/invite-link`);
                                  setLoginFor(null);
                                  setLink({ email: result.email, url: result.invite_link });
                                })
                              }
                            >
                              Invite link
                            </Button>
                          </>
                        )}
                        {r.id !== me?.user.id && (
                          <Button
                            variant="ghost"
                            className="!px-2 !py-1 text-xs"
                            onClick={() => action.run(() => apiPatch(`/api/admin/users/${r.id}`, { is_active: !r.is_active }))}
                          >
                            {r.is_active ? "Deactivate" : "Re-activate"}
                          </Button>
                        )}
                      </div>
                    ),
                  },
                ]}
              />
            )
          }
        </Async>
      </Card>
    </>
  );
}
