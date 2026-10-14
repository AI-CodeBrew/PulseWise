"use client";

import { useState, type FormEvent } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import { Button, Message, TextArea, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiPatch } from "@/lib/api";
import type { AdminSetting, ListResponse } from "@/lib/types";

export default function SettingsPage() {
  const settings = useApi<ListResponse<AdminSetting>>("/api/admin/settings");

  return (
    <>
      <PageHeader title="Settings" description="Numbers and texts the system uses. Anything you leave alone keeps its default." />
      <Async query={settings} skeleton={<Card className="pt-4"><SkeletonRows rows={5} /></Card>}>
        {(s) => <SettingsForm settings={s.results} reload={settings.reload} />}
      </Async>
    </>
  );
}

function SettingsForm({ settings, reload }: { settings: AdminSetting[]; reload: () => void }) {
  // The form keeps everything as text while you type; the backend checks the numbers.
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(settings.map((s) => [s.key, String(s.value)])));
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    const changed: Record<string, string | number | boolean> = {};
    for (const s of settings) {
      const raw = values[s.key] ?? "";
      if (raw === String(s.value)) continue;
      changed[s.key] = s.kind === "int" || s.kind === "float" ? Number(raw) : s.kind === "bool" ? raw === "true" : raw;
    }
    if (Object.keys(changed).length > 0) await apiPatch("/api/admin/settings", { values: changed });
    setSaved(true);
    reload();
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaved(false);
    save.run();
  }

  const groups = [...new Set(settings.map((s) => s.group))];
  return (
    <form onSubmit={onSubmit} className="space-y-6">
      {groups.map((group) => (
        <Card key={group}>
          <CardHeader title={group} />
          <div className="grid gap-4 px-4 pb-5 sm:grid-cols-2 sm:px-5">
            {settings
              .filter((s) => s.group === group)
              .map((s) => {
                const common = {
                  label: s.label,
                  hint: `${s.help}${s.help ? " " : ""}Default: ${s.default === "" ? "empty" : s.default}.`,
                  value: values[s.key] ?? "",
                };
                if (s.kind === "bool") {
                  return (
                    <label key={s.key} className="flex items-start gap-2 text-sm text-ink sm:col-span-2">
                      <input
                        type="checkbox"
                        checked={values[s.key] === "true"}
                        onChange={(e) => setValues((v) => ({ ...v, [s.key]: String(e.target.checked) }))}
                        className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
                      />
                      <span>
                        {s.label}
                        {s.help && <span className="block text-xs text-muted">{s.help}</span>}
                      </span>
                    </label>
                  );
                }
                return s.kind === "text" ? (
                  <div key={s.key} className="sm:col-span-2">
                    <TextArea {...common} onChange={(e) => setValues((v) => ({ ...v, [s.key]: e.target.value }))} />
                  </div>
                ) : (
                  <TextField
                    key={s.key}
                    {...common}
                    type={s.kind === "line" ? "text" : "number"}
                    min={s.minimum ?? undefined}
                    max={s.maximum ?? undefined}
                    step={s.kind === "float" ? "any" : 1}
                    onChange={(e) => setValues((v) => ({ ...v, [s.key]: e.target.value }))}
                  />
                );
              })}
          </div>
        </Card>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" busy={save.busy}>
          Save settings
        </Button>
        {saved && !save.error && <span className="text-sm text-good">✓ Saved</span>}
      </div>
      {save.error && <Message kind="error">{save.error}</Message>}
    </form>
  );
}
