import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';

interface Props {
  onNewProduct: () => void;
}

export const ProductsHeader = ({ onNewProduct }: Props) => (
  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Produtos</h1>
      <p className="text-muted-foreground">Gerencie o cardápio e complementos</p>
    </div>
    {/* Largura cheia no celular: botão principal da tela, alvo generoso. */}
    <Button onClick={onNewProduct} className="min-h-11 w-full sm:min-h-10 sm:w-auto">
      <Plus className="mr-2 h-4 w-4" />
      Novo Produto
    </Button>
  </div>
);
