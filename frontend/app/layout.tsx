import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthProvider } from "@/components/auth/AuthProvider";
import { FullPageLoading } from "@/components/ui/FullPage";
import { BRAND_NAME } from "@/lib/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: `${BRAND_NAME} — Website analytics`,
  description: "Simple analytics for your website",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        {/*
          Pages read the URL (?days=, ?next=) and load their data in the browser, so the
          whole app sits inside one Suspense boundary (Next.js requires this for
          components that read the URL). AuthProvider knows who is logged in.
        */}
        <Suspense fallback={<FullPageLoading />}>
          <AuthProvider>{children}</AuthProvider>
        </Suspense>
      </body>
    </html>
  );
}
