/**
 * Estado de "salvando..." para formulários que chamam uma mutation e fecham o
 * diálogo ao concluir com sucesso. Existe porque os diálogos de criação/edição
 * do cardápio repetiam o mesmo try/catch/finally; o erro em si já vira toast
 * no hook de dados (`use-products`), aqui só cuidamos do spinner do botão.
 */

import { useState } from 'react';

export function useAsyncSubmit() {
  const [loading, setLoading] = useState(false);

  const run = async (action: () => Promise<unknown>) => {
    setLoading(true);
    try {
      await action();
    } catch {
      // Erro já vira toast no hook de dados; aqui só liberamos o botão.
    } finally {
      setLoading(false);
    }
  };

  return { loading, run };
}
