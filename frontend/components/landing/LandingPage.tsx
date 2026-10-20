import { Plus_Jakarta_Sans } from "next/font/google";
import Link from "next/link";

import { Icon, type IconName } from "@/components/layout/icons";
import { BrandMark } from "@/components/ui/BrandMark";
import { BRAND_NAME } from "@/lib/brand";
import { HERO_BACKGROUND } from "./heroBackground";
import { Pricing } from "./Pricing";

/*
  The public front page (/) for visitors who are not logged in.
  A dark green bar on top (like the app's menu, ".chrome" in globals.css), everything else light (".landing")
  with dark text; HERO_BACKGROUND is the soft green behind the headline and the last banner.
*/

const font = Plus_Jakarta_Sans({ subsets: ["latin"], display: "swap" });

type Feature = { icon: IconName; title: string; text: string; wide?: boolean; chips?: string[] };

const FEATURES: Feature[] = [
  {
    icon: "overview",
    title: "Everything on one page",
    text: "Visitors, top pages and where they come from, at a glance. No digging through menus.",
    wide: true,
    chips: ["Visitors", "Top pages", "Traffic sources", "Countries"],
  },
  { icon: "live", title: "Live, as it happens", text: "See who is on your website right now, and what they are looking at." },
  { icon: "recordings", title: "Watch real visits", text: "Replay visits to see where people click, scroll and leave." },
  { icon: "reports", title: "A report every Monday", text: "A short summary of your week, in plain words, in your inbox." },
  { icon: "audience", title: "Know your audience", text: "Countries, devices and browsers of the people who visit you." },
  {
    icon: "dashboard",
    title: "Your own dashboard",
    text: "Pin the numbers you care about and switch between the last 7 and 30 days.",
    wide: true,
    chips: ["Sessions", "Bounce rate", "Form sent", "7 days | 30 days"],
  },
  { icon: "eyeOff", title: "Only your data", text: "Each business sees its own website and nothing else." },
];

const STEPS = [
  { title: "We connect your website", text: "A small tracking code, added once. Nothing changes for your visitors." },
  { title: "You log in", text: "Your numbers, your pages, your visitors, on one simple dashboard." },
  { title: "A report every Monday", text: "What went up, what went down, and what to look at next." },
];

export function LandingPage() {
  return (
    <div className={`landing ${font.className} min-h-screen bg-page text-ink antialiased`}>
      <Header />
      <Hero />
      <Features />
      <HowItWorks />
      <Pricing />
      <FinalCall />
      <Footer />
    </div>
  );
}

function Header() {
  return (
    <header className="chrome sticky top-0 z-30 border-b border-line bg-[#0a2b20]/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <BrandMark size={32} />
          <span className="text-lg font-bold tracking-tight text-ink">{BRAND_NAME}</span>
        </Link>
        <nav aria-label="Main" className="flex items-center gap-6">
          <a href="#features" className="hidden text-sm font-medium text-ink-2 hover:text-ink sm:inline">
            Features
          </a>
          <a href="#how" className="hidden text-sm font-medium text-ink-2 hover:text-ink sm:inline">
            How it works
          </a>
          <a href="#pricing" className="hidden text-sm font-medium text-ink-2 hover:text-ink sm:inline">
            Pricing
          </a>
          <Link href="/login" className="rounded-full bg-white px-5 py-2 text-sm font-semibold text-[#0a2b20] hover:bg-[#e9fbf2]">
            Log in
          </Link>
        </nav>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section style={{ background: HERO_BACKGROUND }}>
      <div className="mx-auto max-w-6xl px-4 pt-16 text-center sm:px-6 sm:pt-24">
        <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 px-3 py-1 text-xs font-medium text-ink-2">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          Website analytics, made simple
        </p>
        <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-extrabold leading-[1.1] tracking-tight text-ink sm:text-6xl">
          See how your website is doing, <span className="text-accent">in plain words.</span>
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-ink-2 sm:text-lg">
          Visitors, top pages, where people come from and what they do on your website. One clear dashboard, and a short
          report every Monday.
        </p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Link href="/login" className="rounded-full bg-accent px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-black/10 hover:opacity-90">
            Log in to your dashboard
          </Link>
          <a href="#how" className="rounded-full border border-line bg-surface px-6 py-3 text-sm font-semibold text-ink hover:bg-surface-2">
            See how it works
          </a>
        </div>
      </div>
      {/* the picture hangs over the edge into the light part below (that part has extra room on top) */}
      <div className="relative z-10 mx-auto -mb-40 mt-14 max-w-5xl px-4 sm:-mb-52 sm:px-6">
        <ProductPicture />
      </div>
    </section>
  );
}

// Made-up numbers for the picture of the dashboard.
const KPIS = [
  { label: "Visitors", value: "12,480", change: "18%" },
  { label: "Sessions", value: "15,902", change: "9%" },
  { label: "Avg. visit", value: "2m 41s", change: "4%" },
];
const LINE = "M0,62 L25,56 L50,59 L75,47 L100,50 L125,40 L150,44 L175,31 L200,35 L225,24 L250,27 L275,14 L300,17";
const PAGES: [string, string, number][] = [
  ["/", "4,210", 100],
  ["/products", "2,840", 67],
  ["/contact", "960", 23],
];
const COUNTRIES: [string, string, number][] = [
  ["Pakistan", "62%", 62],
  ["United Arab Emirates", "14%", 14],
  ["United Kingdom", "9%", 9],
];
const MENU = ["Overview", "Dashboard", "Pages", "Traffic sources", "Sessions", "Recordings", "Weekly reports"];

/** A picture of the dashboard (made-up numbers), drawn with plain HTML so it stays sharp at any size. */
function ProductPicture() {
  return (
    <div aria-hidden="true" className="overflow-hidden rounded-2xl border border-black/5 bg-white text-left shadow-2xl shadow-black/15">
      <div className="flex items-center gap-1.5 border-b border-black/5 bg-[#f3f6f4] px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#d4dbd7]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#d4dbd7]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#d4dbd7]" />
        <span className="ml-3 rounded-md bg-white px-3 py-0.5 text-[11px] text-[#5f6d66]">Example dashboard</span>
      </div>
      <div className="flex">
        <div className="hidden w-40 shrink-0 bg-[#0f3d2e] p-3 sm:block">
          <div className="flex items-center gap-2 px-1 pb-3 text-xs font-bold text-white">
            <BrandMark size={18} />
            {BRAND_NAME}
          </div>
          {MENU.map((item, i) => (
            <div key={item} className={`rounded-md px-2 py-1.5 text-[11px] ${i === 0 ? "bg-[#a7f3d0]/15 font-semibold text-[#a7f3d0]" : "text-[#c2e6d4]"}`}>
              {item}
            </div>
          ))}
        </div>
        <div className="min-w-0 flex-1 bg-[#f4f7f5] p-3 sm:p-4">
          <div className="grid grid-cols-3 gap-2 sm:gap-3">
            {KPIS.map((kpi) => (
              <div key={kpi.label} className="rounded-lg bg-white p-2.5 shadow-sm sm:p-3">
                <p className="truncate text-[10px] text-[#5f6d66] sm:text-xs">{kpi.label}</p>
                <p className="mt-1 text-sm font-bold text-[#0b1f17] sm:text-xl">{kpi.value}</p>
                <p className="mt-0.5 text-[10px] font-semibold text-[#0f6b4a] sm:text-xs">▲ {kpi.change}</p>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded-lg bg-white p-3 shadow-sm">
            <div className="flex items-center justify-between text-[11px] text-[#5f6d66]">
              <span className="font-semibold text-[#0b1f17]">Visitors</span>
              <span>Last 30 days</span>
            </div>
            <svg viewBox="0 0 300 80" preserveAspectRatio="none" className="mt-2 h-28 w-full sm:h-36">
              <defs>
                <linearGradient id="landing-chart-fill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#0f6b4a" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#0f6b4a" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d={`${LINE} L300,80 L0,80 Z`} fill="url(#landing-chart-fill)" />
              <path d={LINE} fill="none" stroke="#0f6b4a" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
            </svg>
          </div>
          <div className="mt-3 hidden grid-cols-2 gap-3 sm:grid">
            <MiniList title="Top pages" rows={PAGES} />
            <MiniList title="Countries" rows={COUNTRIES} />
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniList({ title, rows }: { title: string; rows: [string, string, number][] }) {
  return (
    <div className="rounded-lg bg-white p-3 shadow-sm">
      <p className="text-[11px] font-semibold text-[#0b1f17]">{title}</p>
      <ul className="mt-2 space-y-1.5">
        {rows.map(([name, value, share]) => (
          <li key={name} className="relative overflow-hidden rounded px-2 py-1 text-[11px]">
            <span className="absolute inset-y-0 left-0 bg-[#0f6b4a]/10" style={{ width: `${share}%` }} />
            <span className="relative flex justify-between gap-2 text-[#0b1f17]">
              <span className="truncate">{name}</span>
              <span className="font-semibold">{value}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Features() {
  return (
    <section id="features" className="scroll-mt-20 bg-page pb-20 pt-56 sm:pb-28 sm:pt-72">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold text-accent">Everything in one place</p>
          <h2 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">All you need to know about your visitors</h2>
          <p className="mt-4 text-ink-2">No setup on your side and nothing to learn. Open your dashboard and the answers are there.</p>
        </div>
        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <div
              key={feature.title}
              className={`rounded-2xl border border-line bg-surface p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${feature.wide ? "lg:col-span-2" : ""}`}
            >
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-accent-soft text-accent">
                <Icon name={feature.icon} />
              </span>
              <h3 className="mt-5 text-lg font-bold">{feature.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{feature.text}</p>
              {feature.chips && (
                <div className="mt-5 flex flex-wrap gap-2">
                  {feature.chips.map((chip) => (
                    <span key={chip} className="rounded-full border border-line bg-page px-3 py-1 text-xs font-medium text-ink-2">
                      {chip}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-20 bg-surface py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold text-accent">How it works</p>
          <h2 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">Up and running in three steps</h2>
        </div>
        <ol className="relative mt-14 grid gap-10 sm:grid-cols-3">
          <span aria-hidden="true" className="absolute left-[17%] right-[17%] top-6 hidden border-t border-dashed border-accent/40 sm:block" />
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative text-center">
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-accent text-base font-bold text-white ring-8 ring-surface">
                {i + 1}
              </span>
              <h3 className="mt-5 text-lg font-bold">{step.title}</h3>
              <p className="mx-auto mt-1.5 max-w-xs text-sm leading-relaxed text-ink-2">{step.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function FinalCall() {
  return (
    <section className="bg-surface pb-20 sm:pb-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="rounded-3xl px-6 py-14 text-center sm:px-12" style={{ background: HERO_BACKGROUND }}>
          <h2 className="mx-auto max-w-2xl text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">Your website, explained every Monday.</h2>
          <p className="mx-auto mt-4 max-w-xl text-ink-2">Log in to see how your website is doing today.</p>
          <Link href="/login" className="mt-8 inline-block rounded-full bg-accent px-7 py-3 text-sm font-semibold text-white hover:opacity-90">
            Log in
          </Link>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-line bg-page">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-8 text-sm text-muted sm:px-6">
        <span className="flex items-center gap-2 font-semibold text-ink">
          <BrandMark size={22} />
          {BRAND_NAME}
        </span>
        <span>
          © {new Date().getFullYear()} {BRAND_NAME}. Website analytics, made simple.
        </span>
        <Link href="/login" className="font-medium text-accent hover:underline">
          Log in
        </Link>
      </div>
    </footer>
  );
}
