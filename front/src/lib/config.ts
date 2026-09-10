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
