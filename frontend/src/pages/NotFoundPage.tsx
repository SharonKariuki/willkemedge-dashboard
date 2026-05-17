import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui";

export default function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-ink-500">
        404
      </p>
      <h1 className="font-display text-3xl font-semibold text-ink-900">
        That page isn't here.
      </h1>
      <p className="max-w-md text-sm text-ink-600">
        The link may be stale, or the page may have moved. From the dashboard
        you can find buildings, tenants, payments, and reports.
      </p>
      <div className="mt-2 flex gap-2">
        <Button onClick={() => navigate("/dashboard")}>Back to dashboard</Button>
      </div>
    </div>
  );
}
