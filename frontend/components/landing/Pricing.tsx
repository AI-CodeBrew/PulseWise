"use client";

import { useState } from "react";

import { useApi } from "@/hooks/useApi";
import { FEATURE_LABELS } from "@/lib/features";
import { formatMoney, formatNumber } from "@/lib/format";
import type { ClientPlan, Currency, FeatureName, SupportInfo } from "@/lib/types";

// The plans for sale (set up in Admin -> Plans), on the landing page. Nothing is shown while there are none.

type PublicPlans = { currency: Currency; plans: ClientPlan[]; support: SupportInfo };

const FEATURE_KEYS = Object.keys(FEATURE_LABELS) as FeatureName[];

/** "$29" instead of "$29.00" for round prices. */
const money = (amount: number, currency: Currency) => formatMoney(amount, currency).replace(/\.00$/, "");

/** "3 websites", "1 website", "Unlimited websites" */
function count(limit: number | null, one: string, many: string): string {
  if (limit === null) return `Unlimited ${many}`;
  return `${formatNumber(limit)} ${limit === 1 ? one : many}`;
}

/** "Get started": a WhatsApp chat (or an email) to us with the message already written; the login page if neither is set. */
function askLink(support: SupportInfo, plan: ClientPlan): { href: string; external: boolean } {
  const message = `Hello, I am interested in the ${plan.name} plan.`;
  const digits = support.whatsapp.replace(/\D/g, "");
  if (digits) return { href: `https://wa.me/${digits}?text=${encodeURIComponent(message)}`, external: true };
  if (support.email) return { href: `mailto:${support.email}?subject=${encodeURIComponent(`${plan.name} plan`)}&body=${encodeURIComponent(message)}`, external: true };
  return { href: "/login", external: false };
}

export function Pricing() {
  const [currency, setCurrency] = useState<Currency>("USD");
  const { data } = useApi<PublicPlans>("/api/public/plans", { currency });
  if (!data || data.plans.length === 0) return null;

  return (
    <section id="pricing" className="scroll-mt-20 bg-page py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold text-accent">Pricing</p>
          <h2 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">Pick the plan that fits your website</h2>
          <p className="mt-4 text-ink-2">Prices are per month. We set everything up for you.</p>
          <div role="group" aria-label="Currency" className="mt-6 inline-flex rounded-full border border-line bg-surface p-1 text-sm">
            {(["USD", "PKR"] as Currency[]).map((c) => (
              <button
                key={c}
                type="button"
                aria-pressed={currency === c}
                onClick={() => setCurrency(c)}
                className={`rounded-full px-4 py-1.5 font-semibold ${currency === c ? "bg-accent text-white" : "text-ink-2 hover:text-ink"}`}
              >
                {c === "USD" ? "US$" : "PKR"}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {data.plans.map((plan) => {
            const ask = askLink(data.support, plan);
            return (
              <article key={plan.id} aria-label={`${plan.name} plan`} className="flex flex-col rounded-2xl border border-line bg-surface p-6 shadow-sm">
                <h3 className="text-lg font-bold">{plan.name}</h3>
                {plan.description && <p className="mt-1 text-sm text-ink-2">{plan.description}</p>}
                <p className="mt-5">
                  <span className="text-4xl font-extrabold tracking-tight tabular-nums">{money(plan.price, data.currency)}</span>
                  <span className="text-sm text-ink-2"> / month</span>
                </p>
                {plan.intro_price !== null && (
                  <p className="mt-1 text-sm font-semibold text-accent">
                    {plan.intro_months === 1 ? "First month" : `First ${plan.intro_months} months`}: {money(plan.intro_price, data.currency)}
                  </p>
                )}

                <ul className="mt-6 space-y-2 border-t border-line pt-5 text-sm">
                  <li>{plan.monthly_event_limit === null ? "Unlimited events" : `${formatNumber(plan.monthly_event_limit)} events a month`}</li>
                  {plan.features.recordings && (
                    <li>{plan.monthly_recording_limit === null ? "Unlimited recordings" : `${formatNumber(plan.monthly_recording_limit)} recordings a month`}</li>
                  )}
                  <li>{count(plan.max_websites, "website", "websites")}</li>
                  <li>{count(plan.max_team_members, "person with access", "people with access")}</li>
                </ul>
                <ul className="mt-4 space-y-2 text-sm">
                  {FEATURE_KEYS.map((feature) => (
                    <li key={feature} className={`flex gap-2 ${plan.features[feature] ? "text-ink" : "text-muted line-through decoration-1"}`}>
                      <span aria-hidden="true" className={plan.features[feature] ? "font-bold text-accent" : ""}>
                        {plan.features[feature] ? "✓" : "✕"}
                      </span>
                      {FEATURE_LABELS[feature]}
                      <span className="sr-only">{plan.features[feature] ? " (included)" : " (not included)"}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-auto pt-7">
                  <a
                    href={ask.href}
                    {...(ask.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                    className="block rounded-full bg-accent px-5 py-3 text-center text-sm font-semibold text-white hover:opacity-90"
                  >
                    Get started
                  </a>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
