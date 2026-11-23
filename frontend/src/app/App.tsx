import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { AppLayout } from "@/components/layout/AppLayout";
import { LoadingState } from "@/components/common/common";
import { createQueryClient } from "./query-client";

const page = (loader: () => Promise<{ default: React.ComponentType }>) => {
  const C = lazy(loader);
  return (
    <Suspense fallback={<LoadingState />}>
      <C />
    </Suspense>
  );
};

const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: page(() => import("@/pages/DashboardPage")) },
      { path: "/calendar", element: page(() => import("@/pages/CalendarPage")) },
      { path: "/studio/:storyId?", element: page(() => import("@/pages/ContentStudioPage")) },
      { path: "/approvals", element: page(() => import("@/pages/ApprovalCentrePage")) },
      { path: "/safety", element: page(() => import("@/pages/SafetyReviewPage")) },
      { path: "/publishing", element: page(() => import("@/pages/PublishingMonitorPage")) },
      { path: "/distribution", element: page(() => import("@/pages/DistributionPage")) },
      { path: "/agents", element: page(() => import("@/pages/AgentMonitorPage")) },
      { path: "/analytics", element: page(() => import("@/pages/AnalyticsPage")) },
      { path: "/logs", element: page(() => import("@/pages/ActivityLogsPage")) },
      { path: "/settings", element: page(() => import("@/pages/SettingsPage")) },
    ],
  },
]);

const queryClient = createQueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster theme="dark" position="bottom-right" richColors closeButton />
    </QueryClientProvider>
  );
}
