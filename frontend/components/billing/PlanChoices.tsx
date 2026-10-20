"use client";

import { Badge } from "@/components/ui/Form";
import { Card, CardHeader } from "@/components/ui/Card";
import { FEATURE_LABELS } from "@/lib/features";
import { formatMoney, formatNumber } from "@/lib/format";
import type { ClientPlan, Currency, FeatureName, SupportInfo } from "@/lib/types";

const FEATURE_KEYS = Object.keys(FEATURE_LABELS) as FeatureName[];

/** "3 websites", "1 website", "Unlimited websites" */
function count(limit: number | null, one: string, many: string): string {
  if (limit === null) return `Unlimited ${many}`;
  return `${formatNumber(limit)} ${limit === 1 ? one : many}`;
}

/**
 * "Ask for this plan": a WhatsApp chat (or an email) to us with the message already written.
 * Plans are switched by us in the admin panel, so asking is all a client has to do.
 */
function askLink(support: SupportInfo | undefined, businessName: string, plan: ClientPlan): string | null {
  const message = `Hello, I would like to switch ${businessName} to the ${plan.name} plan.`;
  const digits = support?.whatsapp.replace(/\D/g, "");
  if (digits) return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
  if (support?.email) return `mailto:${support.email}?subject=${encodeURIComponent(`${plan.name} plan`)}&body=${encodeURIComponent(message)}`;
  return null;
}

/** The plans a client can choose from: price, first-month price, what is included. The plan they are on is marked. */
export function PlanChoices({
  plans,
  currentPlanId,
  currency,
  businessName,
  support,
}: {
  plans: ClientPlan[];
  currentPlanId: string | null;
  currency: Currency;
  businessName: string;
  support: SupportInfo | undefined;
}) {
  if (plans.length === 0) return null;
  const money = (amount: number) => formatMoney(amount, currency);
  return (
    <Card>
      <CardHeader title="Plans" subtitle="What each plan includes. Prices are per month. Tell us which one you want and we will set it up." />
      <div className="grid gap-4 px-4 pb-5 sm:grid-cols-2 sm:px-5 xl:grid-cols-3">
        {plans.map((plan) => {
          const current = plan.id === currentPlanId;
          const ask = current ? null : askLink(support, businessName, plan);
          return (
            <article
              key={plan.id}
              data-plan={plan.name}
              aria-label={`${plan.name} plan`}
              className={`flex flex-col rounded-xl border p-4 ${current ? "border-accent bg-accent-soft" : "border-line"}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-ink">{plan.name}</h3>
                {current && <Badge tone="blue">Your plan</Badge>}
              </div>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-ink">
                {money(plan.price)} <span className="text-sm font-normal text-ink-2">per month</span>
              </p>
              {plan.intro_price !== null && (
                <p className="text-sm text-ink-2">
                  {plan.intro_months === 1 ? "First month" : `First ${plan.intro_months} months`}: <strong className="text-ink">{money(plan.intro_price)}</strong>
                </p>
              )}
              {plan.description && <p className="mt-2 text-sm text-ink-2">{plan.description}</p>}
              <ul className="mt-3 space-y-1 text-sm text-ink">
                <li>{plan.monthly_event_limit === null ? "Unlimited events" : `${formatNumber(plan.monthly_event_limit)} events a month`}</li>
                {plan.features.recordings && (
                  <li>{plan.monthly_recording_limit === null ? "Unlimited recordings (videos)" : `${formatNumber(plan.monthly_recording_limit)} recordings (videos) a month`}</li>
                )}
                <li>{count(plan.max_websites, "website", "websites")}</li>
                <li>{count(plan.max_team_members, "person with access", "people with access")}</li>
              </ul>
              <ul className="mt-3 grid grid-cols-1 gap-1 text-sm">
                {FEATURE_KEYS.map((feature) => (
                  <li key={feature} className={plan.features[feature] ? "text-ink" : "text-muted"}>
                    <span aria-hidden="true">{plan.features[feature] ? "✓" : "✕"}</span> {FEATURE_LABELS[feature]}
                    <span className="sr-only">{plan.features[feature] ? " (included)" : " (not included)"}</span>
                  </li>
                ))}
              </ul>
              {ask && (
                <div className="mt-auto pt-4">
                  <a
                    href={ask}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:opacity-90"
                  >
                    Ask for this plan
                  </a>
                </div>
              )}
            </article>
          );
        })}
      </div>
    </Card>
  );
}
