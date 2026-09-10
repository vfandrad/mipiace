import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';

interface Props {
  onNewProduct: () => void;
}

export const ProductsHeader = ({ onNewProduct }: Props) => (
  <div className="flex items-center justify-between">
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Produtos</h1>
      <p className="text-muted-foreground">Gerencie o cardápio e complementos</p>
    </div>
    <Button onClick={onNewProduct}>
      <Plus className="h-4 w-4 mr-2" />
      Novo Produto
    </Button>
  </div>
);
