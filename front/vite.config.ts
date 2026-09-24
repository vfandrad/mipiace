import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

/**
 * Troca `%STORE_NAME%` no index.html pelo nome configurado.
 *
 * O `<title>` é a única parte da interface que o React não renderiza, então
 * sem isto o nome da loja precisaria estar escrito no HTML — e trocar de
 * cliente voltaria a ser editar arquivo.
 */
function storeName(name: string): Plugin {
  return {
    name: "store-name",
    transformIndexHtml: (html) => html.replaceAll("%STORE_NAME%", name),
  };
}

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    // Mesma porta usada pelo container do front no docker compose da raiz.
    port: 8080,
    hmr: {
      overlay: false,
    },
  },
  preview: {
    host: "::",
    port: 8080,
  },
  plugins: [react(), storeName(loadEnv(mode, process.cwd(), "").VITE_STORE_NAME || "Mi Piace Gelateria")],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
