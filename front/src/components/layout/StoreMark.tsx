/**
 * A marca da loja no cabeçalho: logo se houver, nome se não.
 *
 * Nome e logo vêm do ambiente (`VITE_STORE_NAME`, `VITE_STORE_LOGO_URL`)
 * porque o painel não é de uma empresa só — a Mi Piace é o primeiro cliente,
 * não o produto. Sem logo configurado o cabeçalho mostra o nome, que é o que
 * uma casa nova tem no primeiro dia.
 */

import { STORE_LOGO_URL, STORE_NAME } from '@/lib/config';

export function StoreMark() {
  if (!STORE_LOGO_URL) {
    return (
      <span className="truncate text-lg font-semibold tracking-tight sm:text-xl">
        {STORE_NAME}
      </span>
    );
  }
  return (
    <img src={STORE_LOGO_URL} alt={STORE_NAME} className="h-8 object-contain sm:h-10" />
  );
}
