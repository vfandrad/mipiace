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
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type { ProductInput } from '@/types/catalog';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (data: ProductInput) => Promise<unknown>;
}

export const CreateProductDialog = ({ open, onOpenChange, onCreate }: Props) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [price, setPrice] = useState('');
  const [available, setAvailable] = useState(true);
  const { loading, run } = useAsyncSubmit();

  const handleSubmit = () => {
    if (!name.trim()) return;
    run(async () => {
      await onCreate({
        name: name.trim(),
        description: description.trim() || null,
        base_price: Number.parseFloat(price) || 0,
        is_available: available,
      });
      setName('');
      setDescription('');
      setPrice('');
      setAvailable(true);
      onOpenChange(false);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Novo produto</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="product-name">Nome</Label>
            <Input
              id="product-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Pote 500ml"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product-description">Descrição (opcional)</Label>
            <Textarea
              id="product-description"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Aparece no cardápio que o agente manda pelo WhatsApp"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product-price">Preço base (R$)</Label>
            <Input
              id="product-price"
              type="number"
              step="0.01"
              min={0}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="0,00"
            />
          </div>
          <div className="flex items-center justify-between">
            <Label htmlFor="product-available">Disponível</Label>
            <Switch id="product-available" checked={available} onCheckedChange={setAvailable} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !name.trim()}>
            {loading ? 'Criando...' : 'Criar produto'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
