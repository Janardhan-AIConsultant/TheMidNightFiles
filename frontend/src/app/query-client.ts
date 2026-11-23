import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { toApiError } from "@/services/client";

/** Mutation failures (including backend eligibility rejections) are surfaced centrally. */
export function notifyError(err: unknown) {
  const e = toApiError(err);
  toast.error(e.message, { description: e.reasons.length ? e.reasons.join(" · ") : undefined });
}

export const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        retry: (count, err) => count < 2 && !["invalid_response", "http_error"].includes(toApiError(err).code) && (toApiError(err).status ?? 500) >= 500,
        refetchOnWindowFocus: false,
      },
    },
    mutationCache: new MutationCache({ onError: (err, _v, _c, mutation) => !mutation.meta?.silent && notifyError(err) }),
  });
