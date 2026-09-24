/**
 * Cabeçalho da tela de Produtos: título e as três ações da página.
 *
 * O título e a linha de ações em si vêm do `PageTitle` — era o mesmo bloco de
 * markup repetido em todas as telas. O que sobrou aqui é só o que é desta
 * tela: quais são os botões.
 */

import { Button } from '@/components/ui/button';
import { Plus, Tags } from 'lucide-react';
import { PageTitle } from '@/components/layout/Page';
import { RefreshButton } from '@/components/common/RefreshButton';

interface Props {
  onNewProduct: () => void;
  onManageCategories: () => void;
  onRefresh: () => unknown;
}

export const ProductsHeader = ({ onNewProduct, onManageCategories, onRefresh }: Props) => (
  <PageTitle
    title="Produtos"
    subtitle="Gerencie o cardápio e complementos"
    actions={
      <>
        <RefreshButton onRefresh={onRefresh} />
        <Button
          variant="outline"
          onClick={onManageCategories}
          className="min-h-11 sm:min-h-10"
        >
          <Tags className="mr-2 h-4 w-4" />
          <span className="hidden sm:inline">Categorias de item</span>
          <span className="sm:hidden">Categorias</span>
        </Button>
        {/* Botão principal da tela: ocupa o resto da faixa no celular. */}
        <Button onClick={onNewProduct} className="min-h-11 flex-1 sm:min-h-10 sm:flex-none">
          <Plus className="mr-2 h-4 w-4" />
          Novo Produto
        </Button>
      </>
    }
  />
);
