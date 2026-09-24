/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base da API FastAPI. Ex.: http://localhost:8000 */
  readonly VITE_API_BASE_URL?: string;
  /** Valor enviado no header X-API-Key das rotas administrativas. */
  readonly VITE_ADMIN_API_KEY?: string;
  /** Nome da loja, exibido no cabeçalho e nos títulos. */
  readonly VITE_STORE_NAME?: string;
  /** URL do logo. Vazio = mostra o nome da loja em texto. */
  readonly VITE_STORE_LOGO_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
