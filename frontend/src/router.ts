import {
  createRouter,
  createWebHistory,
  type Router,
  type RouteRecordRaw,
} from "vue-router";

export type AppRoute =
  | { name: "login" }
  | { name: "register" }
  | { name: "case-list" }
  | { name: "case-create" }
  | { name: "case-detail"; gameId: number }
  | { name: "not-found" };

const RETURN_PATH_KEY = "ai_mm_return_path";

export function parseAppRoute(pathname: string): AppRoute {
  if (pathname === "/" || pathname === "/login") return { name: "login" };
  if (pathname === "/register") return { name: "register" };
  if (pathname === "/cases") return { name: "case-list" };
  if (pathname === "/cases/new") return { name: "case-create" };
  const gameMatch = pathname.match(/^\/cases\/([1-9]\d*)$/);
  if (gameMatch) return { name: "case-detail", gameId: Number(gameMatch[1]) };
  return { name: "not-found" };
}

export function appRoutePath(route: Exclude<AppRoute, { name: "not-found" }>): string {
  switch (route.name) {
    case "login":
      return "/login";
    case "register":
      return "/register";
    case "case-list":
      return "/cases";
    case "case-create":
      return "/cases/new";
    case "case-detail":
      return `/cases/${route.gameId}`;
  }
}

export function isPrivateRoute(route: AppRoute): boolean {
  return route.name === "case-list"
    || route.name === "case-create"
    || route.name === "case-detail";
}

export function isSafeReturnPath(pathname: string): boolean {
  return isPrivateRoute(parseAppRoute(pathname));
}

const routeRecords: RouteRecordRaw[] = [
  { path: "/", redirect: "/login" },
  { path: "/login", name: "login", component: { render: () => null } },
  { path: "/register", name: "register", component: { render: () => null } },
  { path: "/cases", name: "case-list", component: { render: () => null } },
  { path: "/cases/new", name: "case-create", component: { render: () => null } },
  { path: "/cases/:gameId(\\d+)", name: "case-detail", component: { render: () => null } },
  { path: "/:pathMatch(.*)*", name: "not-found", component: { render: () => null } },
];

export function createAppRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: routeRecords,
  });
}

export function createBrowserRouter(router: Router) {
  return {
    current(): AppRoute {
      return parseAppRoute(window.location.pathname);
    },
    async push(route: Exclude<AppRoute, { name: "not-found" }>): Promise<void> {
      const path = appRoutePath(route);
      if (window.location.pathname !== path) await router.push(path);
    },
    async replace(route: Exclude<AppRoute, { name: "not-found" }>): Promise<void> {
      const path = appRoutePath(route);
      if (window.location.pathname !== path) await router.replace(path);
    },
    rememberCurrentReturnPath(): void {
      if (isSafeReturnPath(window.location.pathname)) {
        window.sessionStorage.setItem(RETURN_PATH_KEY, window.location.pathname);
      }
    },
    consumeReturnPath(): string {
      const path = window.sessionStorage.getItem(RETURN_PATH_KEY) || "";
      window.sessionStorage.removeItem(RETURN_PATH_KEY);
      return isSafeReturnPath(path) ? path : "";
    },
    clearReturnPath(): void {
      window.sessionStorage.removeItem(RETURN_PATH_KEY);
    },
    async replacePath(path: string): Promise<void> {
      if (isSafeReturnPath(path) && window.location.pathname !== path) {
        await router.replace(path);
      }
    },
  };
}
