import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/vue-query";
import { computed, type ComputedRef } from "vue";

import { getApiClient } from "../runtime";
import { useAuthStore } from "../stores/auth";

export interface GameSummary {
  id: number;
  title: string;
  category: string;
  mode: string;
  player_role_id: string | null;
  ai_agent_count: number;
  current_stage: number;
  current_phase: string;
  total_stages: number;
  status: string;
  created_at: string;
  updated_at: string;
  lifecycle_version?: number;
  catalog_script_id?: string | null;
}

export const gameRecordsQueryKey = (userId: number) => ["game-records", userId] as const;

export function invalidateGameRecords(queryClient: QueryClient, userId: number): Promise<void> {
  return queryClient.invalidateQueries({
    queryKey: gameRecordsQueryKey(userId),
    refetchType: "none",
  });
}

export function useGameRecordsQuery(enabled: ComputedRef<boolean>) {
  const auth = useAuthStore();
  const queryClient = useQueryClient();
  const queryKey = computed(() => gameRecordsQueryKey(auth.user?.id || 0));

  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => getApiClient().request<GameSummary[]>("/api/games", { signal }),
    enabled: computed(() => enabled.value && Boolean(auth.user)),
  });

  const deletion = useMutation({
    mutationKey: ["delete-game-record"],
    mutationFn: async (game: GameSummary) => {
      await getApiClient().request(`/api/games/${game.id}`, { method: "DELETE" });
      return game;
    },
    onMutate: async (game) => {
      const key = queryKey.value;
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<GameSummary[]>(key);
      queryClient.setQueryData<GameSummary[]>(key, (records = []) => (
        records.filter((record) => record.id !== game.id)
      ));
      return { key, previous };
    },
    onError: (_error, _game, context) => {
      if (context?.previous) queryClient.setQueryData(context.key, context.previous);
    },
    onSettled: (_data, _error, _game, context) => {
      void queryClient.invalidateQueries({ queryKey: context?.key || queryKey.value });
    },
  });

  return {
    ...query,
    deleteRecord: deletion.mutateAsync,
    deletingGameId: computed(() => (
      deletion.isPending.value ? deletion.variables.value?.id ?? null : null
    )),
    invalidate: () => {
      const userId = auth.user?.id;
      return userId ? invalidateGameRecords(queryClient, userId) : Promise.resolve();
    },
  };
}

export function queryErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "读取案件档案失败";
}
