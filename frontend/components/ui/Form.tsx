"use client";

// Small building blocks for forms and buttons, used by the admin panel (and later by the client settings).

import { useCallback, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { PasswordInput } from "@/components/ui/PasswordInput";
import { ApiError } from "@/lib/api";

const inputClass =
  "w-full rounded-lg border border-line bg-page px-3 py-2 text-sm text-ink outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent-soft disabled:opacity-60";

/**
 * A labelled text box. A box with type="password" (passwords, API keys) gets the eye button that shows/hides it;
 * `shown` / `onShownChange` are only for a page that wants to know or set that (see "Add user").
 */
export function TextField({
  label,
  hint,
  shown,
  onShownChange,
  ...input
}: { label: string; hint?: string; shown?: boolean; onShownChange?: (shown: boolean) => void } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      {input.type === "password" ? (
        // aria-label: the eye button lives inside this <label>, so name the box explicitly (else it would read "Password Show password")
        <PasswordInput {...input} aria-label={label} shown={shown} onShownChange={onShownChange} className={inputClass} />
      ) : (
        <input {...input} className={inputClass} />
      )}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function TextArea({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      <textarea {...input} className={`${inputClass} min-h-20`} />
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function SelectField({
  label,
  children,
  hint,
  ...input
}: { label: string; hint?: string; children: ReactNode } & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      <select {...input} className={inputClass}>
        {children}
      </select>
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-white hover:opacity-90",
  secondary: "border border-line bg-surface text-ink hover:bg-surface-2",
  danger: "bg-bad text-white hover:opacity-90",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
};

export function Button({
  variant = "secondary",
  busy = false,
  children,
  className = "",
  ...props
}: { variant?: Variant; busy?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      disabled={busy || props.disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium disabled:opacity-60 ${variants[variant]} ${className}`}
    >
      {busy ? "Please wait…" : children}
    </button>
  );
}

type Tone = "green" | "amber" | "red" | "gray" | "blue";

const tones: Record<Tone, string> = {
  green: "bg-accent-soft text-good",
  amber: "bg-surface-2 text-ink",
  red: "bg-bad-soft text-bad",
  gray: "bg-surface-2 text-ink-2",
  blue: "bg-accent-soft text-accent",
};
// A symbol in front of the text, so the meaning never depends on colour alone.
const toneIcons: Record<Tone, string> = { green: "●", amber: "▲", red: "✕", gray: "○", blue: "●" };

export function Badge({ tone = "gray", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>
      <span aria-hidden="true" className="text-[9px]">
        {toneIcons[tone]}
      </span>
      {children}
    </span>
  );
}

/** Copies text to the clipboard and says so. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this text:", text); // clipboard blocked: let the user copy manually
    }
  }
  return (
    <Button variant="secondary" onClick={copy} className="!px-2.5 !py-1 text-xs">
      {copied ? "Copied ✓" : label}
    </Button>
  );
}

/** A box of code/text with a Copy button. */
export function CodeBlock({ code, label }: { code: string; label?: string }) {
  return (
    <div className="rounded-lg border border-line bg-page">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5">
        <span className="text-xs text-muted">{label ?? "Code"}</span>
        <CopyButton text={code} />
      </div>
      <pre className="max-h-72 overflow-auto p-3 text-xs leading-relaxed text-ink">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function Message({ kind, children }: { kind: "error" | "success" | "info"; children: ReactNode }) {
  const style = kind === "error" ? "bg-bad-soft" : "bg-accent-soft";
  return (
    <p role={kind === "error" ? "alert" : "status"} className={`rounded-lg px-3 py-2 text-sm text-ink ${style}`}>
      {kind === "error" ? "✕ " : kind === "success" ? "✓ " : ""}
      {children}
    </p>
  );
}

/**
 * Runs an async action (a button click, a form submit) and tracks "busy" and "error" for it.
 * Usage: const save = useAction(async () => { await apiPatch(...); });  <Button busy={save.busy} onClick={save.run}>
 */
export function useAction<Args extends unknown[]>(action: (...args: Args) => Promise<unknown>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    async (...args: Args): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        await action(...args);
        return true;
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
        return false;
      } finally {
        setBusy(false);
      }
    },
    [action],
  );
  return { run, busy, error, clearError: () => setError(null) };
}

/** "Type the name to confirm" box for dangerous actions (deleting a client or website). */
export function DangerZone({
  title,
  description,
  confirmName,
  buttonLabel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmName: string;
  buttonLabel: string;
  onConfirm: () => Promise<unknown>;
}) {
  const [typed, setTyped] = useState("");
  const action = useAction(onConfirm);
  return (
    <div className="rounded-xl border border-bad/40 p-4 sm:p-5">
      <h3 className="text-sm font-semibold text-bad">{title}</h3>
      <p className="mt-1 text-sm text-ink-2">{description}</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1">
          <TextField label={`Type "${confirmName}" to confirm`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </div>
        <Button variant="danger" busy={action.busy} disabled={typed !== confirmName} onClick={() => action.run()}>
          {buttonLabel}
        </Button>
      </div>
      {action.error && (
        <div className="mt-3">
          <Message kind="error">{action.error}</Message>
        </div>
      )}
    </div>
  );
}
