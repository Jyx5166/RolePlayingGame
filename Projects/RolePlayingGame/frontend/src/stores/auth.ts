import { defineStore } from "pinia";

import { appEvents } from "../app-events";
import { getApiClient } from "../runtime";

export interface SessionUser {
  id: number;
  username: string;
}

interface SessionPayload extends SessionUser {
  csrf_token?: string;
}

interface AuthResponse {
  user: SessionUser;
  csrf_token: string;
}

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null as SessionUser | null,
    csrfToken: "",
    status: "checking" as "checking" | "anonymous" | "authenticated" | "submitting",
    error: "",
  }),
  actions: {
    setSession(payload: SessionPayload | AuthResponse): void {
      const user = "user" in payload ? payload.user : payload;
      this.user = { id: user.id, username: user.username };
      this.csrfToken = payload.csrf_token || this.csrfToken;
      this.status = "authenticated";
      this.error = "";
    },
    clearSession(): void {
      this.user = null;
      this.csrfToken = "";
      this.status = "anonymous";
      this.error = "";
    },
    async authenticate(mode: "login" | "register", username: string, password: string): Promise<void> {
      this.status = "submitting";
      this.error = "";
      try {
        const result = await getApiClient().request<AuthResponse>(`/api/auth/${mode}`, {
          method: "POST",
          body: JSON.stringify({ username: username.trim(), password }),
        });
        this.setSession(result);
        appEvents.emit("auth:authenticated", { user: result.user });
      } catch (error) {
        this.status = "anonymous";
        this.error = error instanceof Error ? error.message : "认证失败";
      }
    },
    async logout(): Promise<void> {
      this.status = "submitting";
      try {
        await getApiClient().request("/api/auth/logout", { method: "POST" });
      } catch {
        // Local cleanup still applies if the session has already expired.
      } finally {
        this.clearSession();
        appEvents.emit("auth:logout", { preserveReturnPath: false, broadcast: true });
      }
    },
  },
});

export type AuthStore = ReturnType<typeof useAuthStore>;
