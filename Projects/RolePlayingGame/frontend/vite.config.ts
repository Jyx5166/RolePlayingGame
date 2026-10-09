import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ command }) => ({
  define: {
    "process.env.NODE_ENV": JSON.stringify(command === "build" ? "production" : "development"),
  },
  plugins: [
    vue(),
    {
      name: "legacy-shell-dev-entry",
      apply: "serve",
      transformIndexHtml(html) {
        return html
          .replace(/href="\/static\/styles\.css(?:\?v=[a-f0-9]+)?"/, 'href="/styles.css"')
          .replace(
            /<script src="\/static\/app\.js(?:\?v=[a-f0-9]+)?"><\/script>/,
            '<script type="module" src="/src/main.ts"></script>',
          );
      },
    },
  ],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
  build: {
    target: "es2022",
    outDir: ".build",
    emptyOutDir: true,
    sourcemap: true,
    minify: false,
    lib: {
      entry: "src/main.ts",
      name: "RolePlayingGameApp",
      formats: ["iife"],
      fileName: () => "app.js",
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
}));
