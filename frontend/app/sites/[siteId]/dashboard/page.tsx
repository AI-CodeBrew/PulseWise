"use client";

import { MyDashboard } from "@/components/dashboard/MyDashboard";
import { PageHeader } from "@/components/ui/PageHeader";

/** The tiles this person chose (and, the first time, the question which ones they want). */
export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Dashboard" description="The numbers you chose to keep an eye on." />
      <MyDashboard />
    </>
  );
}
