import { useEffect, useState } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type { CatalogEntity, Complement, FlavorCategory, Product } from '@/types/catalog';

interface Props {
  editTarget: { type: 'product' | 'complement'; item: Product | Complement } | null;
  flavorCategories: FlavorCategory[];
  onClose: () => void;
  onSave: (entity: CatalogEntity, id: string, data: Record<string, unknown>) => Promise<unknown>;
}

export const EditItemSheet = ({ editTarget, flavorCategories, onClose, onSave }: Props) => {
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const { loading, run } = useAsyncSubmit();

  useEffect(() => {
    if (!editTarget) return;
    setName(editTarget.item.name);
    setPrice(
      editTarget.type === 'product'
        ? String((editTarget.item as Product).base_price ?? 0)
        : String((editTarget.item as Complement).extra_price ?? 0),
    );
    setCategoryId(
      editTarget.type === 'complement'
        ? ((editTarget.item as Complement).flavor_category_id ?? '')
        : '',
    );
  }, [editTarget]);

  const handleSave = () => {
    if (!editTarget) return;
    run(async () => {
      const data: Record<string, unknown> = { name: name.trim() };
      if (editTarget.type === 'product') {
        data.base_price = Number.parseFloat(price) || 0;
      } else {
        data.extra_price = Number.parseFloat(price) || 0;
        data.flavor_category_id = categoryId || null;
      }
      await onSave(editTarget.type, editTarget.item.id, data);
      onClose();
    });
  };

  return (
    <Sheet open={!!editTarget} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>
            Editar {editTarget?.type === 'product' ? 'produto' : 'complemento'}
          </SheetTitle>
        </SheetHeader>
        <div className="space-y-4 mt-6">
          <div className="space-y-2">
            <Label htmlFor="edit-name">Nome</Label>
            <Input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-price">
              {editTarget?.type === 'product' ? 'Preço base (R$)' : 'Preço extra (R$)'}
            </Label>
            <Input
              id="edit-price"
              type="number"
              step="0.01"
              min={0}
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </div>
          {editTarget?.type === 'complement' && (
            <div className="space-y-2">
              <Label htmlFor="edit-category">Categoria do sabor</Label>
              <Select
                id="edit-category"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">Não se aplica</option>
                {flavorCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            </div>
          )}
          <Button className="w-full" onClick={handleSave} disabled={loading || !name.trim()}>
            {loading ? 'Salvando...' : 'Salvar alterações'}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
};
