import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';
import { RefreshButton } from '@/components/common/RefreshButton';

interface Props {
  onNewProduct: () => void;
  onRefresh: () => unknown;
}

export const ProductsHeader = ({ onNewProduct, onRefresh }: Props) => (
  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Produtos</h1>
      <p className="text-muted-foreground">Gerencie o cardápio e complementos</p>
    </div>
    <div className="flex items-center gap-2">
      <RefreshButton onRefresh={onRefresh} />
      {/* Botão principal da tela: ocupa o resto da faixa no celular. */}
      <Button onClick={onNewProduct} className="min-h-11 flex-1 sm:min-h-10 sm:flex-none">
        <Plus className="mr-2 h-4 w-4" />
        Novo Produto
      </Button>
    </div>
  </div>
);
