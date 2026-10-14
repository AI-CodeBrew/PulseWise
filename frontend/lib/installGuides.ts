// Step-by-step install instructions shown in the admin panel, per platform.
// The tracking snippet itself comes from the backend; these steps tell the person where to paste it.

export interface Guide {
  id: string;
  label: string;
  intro: string;
  steps: string[];
  /** Extra code to show under the steps (e.g. a React example). */
  code?: { label: string; text: string };
  note?: string;
}

export function installGuides(token: string, ingestionHost: string): Guide[] {
  return [
    {
      id: "shopify",
      label: "Shopify",
      intro: "Add the code to the store's theme so every page sends data.",
      steps: [
        "In the Shopify admin, open Online Store → Themes.",
        "Next to the live theme, click the “…” button → Edit code.",
        "Under “Layout”, open theme.liquid.",
        "Paste the tracking code just BEFORE the closing </head> tag.",
        "Click Save, then visit the store in a new tab and click around.",
      ],
      note: "Shopify's checkout pages are locked, so this tracks the storefront (home, collections, products, cart). Order and sales numbers come from the Shopify orders connection instead.",
    },
    {
      id: "wordpress",
      label: "WordPress",
      intro: "The easiest safe way is a small “header scripts” plugin, so theme updates can't remove it.",
      steps: [
        "In WordPress admin, open Plugins → Add New, search for “WPCode – Insert Headers and Footers”, then Install and Activate it.",
        "Open Code Snippets → Header & Footer.",
        "Paste the tracking code into the “Header” box.",
        "Click Save Changes, then visit the website in a new tab and click around.",
      ],
      note: "Prefer editing the theme? Paste the code before </head> in header.php of a child theme. A normal theme update would erase it.",
    },
    {
      id: "html",
      label: "Custom / HTML",
      intro: "For any website where you can edit the page template.",
      steps: [
        "Open the template that every page shares (often a header, layout or index.html file).",
        "Paste the tracking code just BEFORE the closing </head> tag.",
        "Publish the change, then open the website in a new tab and click around.",
      ],
    },
    {
      id: "react",
      label: "React / Next.js",
      intro: "For apps built with a JavaScript framework, use the npm package instead of the snippet.",
      steps: [
        "Run: npm install posthog-js",
        "Next.js 15.3+: create the file instrumentation-client.ts in the project root with the code below. Other frameworks: call posthog.init(...) once when the app starts, in the browser only.",
        "Deploy, then visit the website and click around.",
      ],
      code: {
        label: "instrumentation-client.ts",
        text: `import posthog from "posthog-js";

posthog.init("${token}", {
  api_host: "${ingestionHost}",
  defaults: "2026-05-30",
});`,
      },
    },
  ];
}

/** Things to do once in PostHog for every new project, whatever the platform. */
export const POSTHOG_SETUP_STEPS = [
  "In PostHog, open the project → Settings → Session replay and switch “Record user sessions” on (needed for the Recordings page).",
  "Install the tracking code with one of the guides below.",
  "Visit the website yourself, then press “Check again” above. A green signal means data is arriving.",
];
