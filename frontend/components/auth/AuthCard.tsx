import type { InputHTMLAttributes, ReactNode } from "react";

import { BrandMark } from "@/components/ui/BrandMark";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { BRAND_NAME } from "@/lib/brand";

/** Centered card with the brand on top: used by login, password and account pages. */
export function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <BrandMark size={32} />
          <span className="text-lg font-semibold text-ink">{BRAND_NAME}</span>
        </div>
        <div className="rounded-xl border border-line bg-surface p-6">
          <h1 className="text-lg font-semibold text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </div>
      </div>
    </main>
  );
}

const fieldClass =
  "w-full rounded-lg border border-line bg-page px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft";

/** A labelled text input. A box with type="password" gets the eye button that shows/hides what is typed. */
export function Field({ label, ...input }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="mb-4 block">
      <span className="mb-1 block text-sm font-medium text-ink">{label}</span>
      {input.type === "password" ? (
        // aria-label: the eye button lives inside this <label>, so name the box explicitly (else it would read "Password Show password")
        <PasswordInput {...input} aria-label={label} className={fieldClass} />
      ) : (
        <input {...input} className={fieldClass} />
      )}
    </label>
  );
}

export function SubmitButton({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
    >
      {busy ? "Please wait…" : children}
    </button>
  );
}

/** Red box for form errors, green box for success. */
export function FormMessage({ kind, children }: { kind: "error" | "success"; children: ReactNode }) {
  return (
    <p
      role={kind === "error" ? "alert" : "status"}
      className={`mb-4 rounded-lg px-3 py-2 text-sm ${kind === "error" ? "bg-bad-soft text-ink" : "bg-accent-soft text-ink"}`}
    >
      {children}
    </p>
  );
}
