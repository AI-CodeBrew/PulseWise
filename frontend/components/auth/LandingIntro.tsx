import Link from "next/link";

import { Icon, type IconName } from "@/components/layout/icons";
import { BrandMark } from "@/components/ui/BrandMark";
import { BRAND_NAME } from "@/lib/brand";

// What the product does, in short. (Phones show only the brand and the headline, so the login form stays close.)
const POINTS: { icon: IconName; title: string; text: string }[] = [
  { icon: "overview", title: "Everything on one page", text: "Visitors, pages and traffic sources at a glance." },
  { icon: "recordings", title: "Watch real visits", text: "See where people click, scroll and leave." },
  { icon: "reports", title: "A report every Monday", text: "A short summary of your week, written for you." },
  { icon: "live", title: "Live, as it happens", text: "Who is on your website right now." },
];

/** The text side of the landing / login page. */
export function LandingIntro() {
  return (
    <div className="mx-auto w-full max-w-lg">
      <Link href="/" className="inline-flex items-center gap-2" title="Home">
        <BrandMark size={36} />
        <span className="text-xl font-semibold text-ink">{BRAND_NAME}</span>
      </Link>
      <h2 className="mt-8 text-3xl font-semibold leading-tight tracking-tight text-ink sm:text-4xl lg:mt-12">
        See how your website is doing, <span className="text-accent">in plain words.</span>
      </h2>
      <p className="mt-4 text-base text-ink-2">
        Visitors, top pages, traffic sources and what people do on your website. All on one simple dashboard.
      </p>
      <ul className="mt-10 hidden space-y-5 lg:block">
        {POINTS.map((point) => (
          <li key={point.title} className="flex gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
              <Icon name={point.icon} />
            </span>
            <span>
              <span className="block text-sm font-semibold text-ink">{point.title}</span>
              <span className="block text-sm text-ink-2">{point.text}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
