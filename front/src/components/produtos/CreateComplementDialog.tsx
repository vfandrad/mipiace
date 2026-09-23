import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type { ComplementInput, ComplementCategory } from '@/types/catalog';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groupId: string;
  categories: ComplementCategory[];
  /** O grupo vai na rota (`POST /api/groups/{id}/complements`). */
  onCreate: (groupId: string, data: ComplementInput) => Promise<unknown>;
}

export const CreateComplementDialog = ({
  open,
  onOpenChange,
  groupId,
  categories,
  onCreate,
}: Props) => {
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [available, setAvailable] = useState(true);
  const [categoryId, setCategoryId] = useState('');
  const { loading, run } = useAsyncSubmit();

  const handleSubmit = () => {
    if (!name.trim() || !groupId) return;
    run(async () => {
      await onCreate(groupId, {
        name: name.trim(),
        extra_price: Number.parseFloat(price) || 0,
        is_available: available,
        category_id: categoryId || null,
      });
      setName('');
      setPrice('');
      setAvailable(true);
      setCategoryId('');
      onOpenChange(false);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Novo complemento</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="complement-name">Nome</Label>
            <Input
              id="complement-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Pistache, Calda de chocolate"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="complement-price">Preço extra (R$)</Label>
            <Input
              id="complement-price"
              type="number"
              step="0.01"
              min={0}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="0,00"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="complement-category">Categoria do item</Label>
            <Select
              id="complement-category"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
            >
              <option value="">Não se aplica</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Use em sabores. Complementos que não são sabor (calda, adicional)
              podem ficar em "Não se aplica".
            </p>
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="complement-available">Disponível</Label>
            <Switch
              id="complement-available"
              checked={available}
              onCheckedChange={setAvailable}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !name.trim()}>
            {loading ? 'Criando...' : 'Criar complemento'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
