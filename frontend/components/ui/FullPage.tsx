import Link from "next/link";
import type { ReactNode } from "react";

/** Centered spinner-like placeholder while the app figures out who is logged in. */
export function FullPageLoading() {
  return (
    <div className="grid min-h-screen place-items-center" aria-label="Loading">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-line border-t-accent" />
    </div>
  );
}

/** A centered message with an optional action, for "not found", "suspended", errors... */
export function FullPageMessage({
  title,
  children,
  linkHref,
  linkLabel,
  action,
}: {
  title: string;
  children?: ReactNode;
  linkHref?: string;
  linkLabel?: string;
  action?: ReactNode;
}) {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-md rounded-xl border border-line bg-surface p-6 text-center">
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        {children && <div className="mt-2 text-sm text-ink-2">{children}</div>}
        {(linkHref || action) && (
          <div className="mt-5 flex justify-center gap-3">
            {linkHref && (
              <Link href={linkHref} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90">
                {linkLabel ?? "Continue"}
              </Link>
            )}
            {action}
          </div>
        )}
      </div>
    </div>
  );
}
