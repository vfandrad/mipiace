/**
 * Configuração vinda do ambiente (Vite embute em tempo de build).
 *
 * Existe como módulo separado para poder ser lido/mocado nos testes sem
 * arrastar o cliente HTTP junto.
 */

function readEnv(key: keyof ImportMetaEnv, fallback: string): string {
  const value = import.meta.env?.[key];
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : fallback;
}

/** Sem barra no final: as rotas já começam com "/". */
export const API_BASE_URL = readEnv('VITE_API_BASE_URL', 'http://localhost:8000').replace(/\/+$/, '');

/** Chave administrativa. O backend recusa (401) qualquer rota /api sem ela. */
export const ADMIN_API_KEY = readEnv('VITE_ADMIN_API_KEY', 'dev-local-key');

/**
 * Identidade da loja.
 *
 * O painel serve a qualquer casa do mesmo nicho, então nome e logo vêm do
 * ambiente — do mesmo jeito que `STORE_NAME` no backend. Os defaults são os da
 * Mi Piace de propósito: a generalização trouxe a OPÇÃO de trocar, não a
 * obrigação de configurar. Uma loja nova sobrescreve; sem sobrescrever, o
 * painel continua sendo o da casa que ele atende hoje.
 *
 * Apontando `VITE_STORE_LOGO_URL` para vazio, o cabeçalho mostra o nome em
 * texto — que é o que uma casa nova tem antes de ter arquivo de marca.
 */
export const STORE_NAME = readEnv('VITE_STORE_NAME', 'Mi Piace Gelateria');
export const STORE_LOGO_URL = readEnv('VITE_STORE_LOGO_URL', '/logo-mipiace.png');
