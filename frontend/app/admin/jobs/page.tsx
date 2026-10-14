"use client";

import { Card } from "@/components/ui/Card";
import { Badge, Button, Message, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiPost } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { AdminJob, ListResponse } from "@/lib/types";

const STATUS: Record<string, { tone: "green" | "red" | "amber" | "gray"; label: string }> = {
  ok: { tone: "green", label: "Worked" },
  error: { tone: "red", label: "Failed" },
  running: { tone: "amber", label: "Running…" },
  skipped: { tone: "gray", label: "Skipped" },
};

export default function JobsPage() {
  // Refresh every 5 seconds, so you can watch a job you just started finish.
  const jobs = useApi<ListResponse<AdminJob>>("/api/admin/jobs", undefined, { refreshMs: 5000 });
  const run = useAction(async (name: string) => {
    await apiPost(`/api/admin/jobs/${name}/run`);
    jobs.reload();
  });

  return (
    <>
      <PageHeader title="Background jobs" description="Tasks that run by themselves on a schedule. Every run is recorded here." />
      {run.error && (
        <div className="mb-4">
          <Message kind="error">{run.error}</Message>
        </div>
      )}
      <Async query={jobs} skeleton={<Card className="pt-4"><SkeletonRows rows={3} /></Card>}>
        {(j) => (
          <ul className="space-y-4">
            {j.results.map((job) => {
              const last = job.last_run;
              const status = last ? STATUS[last.status] : null;
              return (
                <li key={job.name}>
                  <Card className="p-4 sm:p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <h2 className="text-sm font-semibold text-ink">{job.title}</h2>
                        <p className="mt-1 text-sm text-ink-2">{job.description}</p>
                        <p className="mt-1 text-xs text-muted">Runs: {job.schedule}</p>
                      </div>
                      <Button variant="secondary" busy={run.busy || last?.status === "running"} onClick={() => run.run(job.name)}>
                        Run now
                      </Button>
                    </div>
                    <div className="mt-3 border-t border-line pt-3 text-sm">
                      {!last || !status ? (
                        <span className="text-muted">Has not run yet.</span>
                      ) : (
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <Badge tone={status.tone}>{status.label}</Badge>
                          <span className="text-ink-2" title={last.started_at ? formatDateTime(last.started_at) : ""}>
                            {last.started_at ? timeAgo(last.started_at) : ""}
                            {last.triggered_by !== "schedule" ? ` · started by ${last.triggered_by}` : ""}
                          </span>
                          {last.message && <span className="break-words text-ink">{last.message}</span>}
                        </div>
                      )}
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </Async>
    </>
  );
}
