/**
 * Edição de qualquer nível do cardápio: produto, categoria do produto (grupo)
 * e complemento/sabor.
 *
 * A regra desta tela: **o que dá para definir na criação tem que dar para
 * editar depois**. Antes daqui só saíam nome e preço, então descrição,
 * disponibilidade, ordem e as regras de escolha do grupo (obrigatório? quantos
 * sabores?) eram definidas uma vez e nunca mais — para trocar "escolha 2
 * sabores" por "escolha 3" o lojista tinha que apagar a categoria inteira e
 * perder os 31 sabores junto.
 */

import { useEffect, useState } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type {
  CatalogEntity,
  Complement,
  ComplementGroup,
  FlavorCategory,
  Product,
} from '@/types/catalog';

export type EditTarget =
  | { type: 'product'; item: Product }
  | { type: 'group'; item: ComplementGroup }
  | { type: 'complement'; item: Complement };

interface Props {
  editTarget: EditTarget | null;
  flavorCategories: FlavorCategory[];
  onClose: () => void;
  onSave: (entity: CatalogEntity, id: string, data: Record<string, unknown>) => Promise<unknown>;
}

const TITULOS: Record<EditTarget['type'], string> = {
  product: 'Editar produto',
  group: 'Editar categoria',
  complement: 'Editar item',
};

/** Campos de todos os níveis num estado só — cada tipo usa os seus. */
interface Form {
  name: string;
  description: string;
  price: string;
  available: boolean;
  sortOrder: string;
  categoryId: string;
  minChoices: string;
  maxChoices: string;
  required: boolean;
}

const VAZIO: Form = {
  name: '',
  description: '',
  price: '0',
  available: true,
  sortOrder: '0',
  categoryId: '',
  minChoices: '0',
  maxChoices: '1',
  required: false,
};

function carregar(target: EditTarget): Form {
  const base = { ...VAZIO, name: target.item.name };

  if (target.type === 'product') {
    const product = target.item;
    return {
      ...base,
      description: product.description ?? '',
      price: String(product.base_price ?? 0),
      available: product.is_available,
      sortOrder: String(product.sort_order ?? 0),
    };
  }

  if (target.type === 'group') {
    const group = target.item;
    return {
      ...base,
      sortOrder: String(group.sort_order ?? 0),
      minChoices: String(group.min_choices),
      maxChoices: String(group.max_choices),
      required: group.is_required,
    };
  }

  const complement = target.item;
  return {
    ...base,
    price: String(complement.extra_price ?? 0),
    available: complement.is_available,
    sortOrder: String(complement.sort_order ?? 0),
    categoryId: complement.flavor_category_id ?? '',
  };
}

function numero(valor: string, minimo = 0): number {
  const parsed = Number.parseInt(valor, 10);
  return Number.isNaN(parsed) ? minimo : Math.max(minimo, parsed);
}

export const EditItemSheet = ({ editTarget, flavorCategories, onClose, onSave }: Props) => {
  const [form, setForm] = useState<Form>(VAZIO);
  const { loading, run } = useAsyncSubmit();

  useEffect(() => {
    if (editTarget) setForm(carregar(editTarget));
  }, [editTarget]);

  const set = <K extends keyof Form>(campo: K, valor: Form[K]) =>
    setForm((atual) => ({ ...atual, [campo]: valor }));

  const min = numero(form.minChoices);
  const max = numero(form.maxChoices, 1);
  // Um grupo obrigatório com mínimo 0 é contraditório, e o backend recusa: o
  // agente decide "falta escolher sabor?" olhando exatamente esse mínimo.
  const erroDeEscolhas =
    editTarget?.type === 'group'
      ? max < min
        ? 'O máximo não pode ser menor que o mínimo.'
        : form.required && min < 1
          ? 'Categoria obrigatória precisa de no mínimo 1 escolha.'
          : null
      : null;

  const handleSave = () => {
    if (!editTarget) return;
    run(async () => {
      const data: Record<string, unknown> = {
        name: form.name.trim(),
        sort_order: numero(form.sortOrder),
      };

      if (editTarget.type === 'product') {
        data.description = form.description.trim() || null;
        data.base_price = Number.parseFloat(form.price) || 0;
        data.is_available = form.available;
      } else if (editTarget.type === 'group') {
        data.min_choices = min;
        data.max_choices = max;
        data.is_required = form.required;
      } else {
        data.extra_price = Number.parseFloat(form.price) || 0;
        data.is_available = form.available;
        data.flavor_category_id = form.categoryId || null;
      }

      await onSave(editTarget.type, editTarget.item.id, data);
      onClose();
    });
  };

  return (
    <Sheet open={!!editTarget} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{editTarget ? TITULOS[editTarget.type] : 'Editar'}</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-4 pb-6">
          <div className="space-y-2">
            <Label htmlFor="edit-name">Nome</Label>
            <Input
              id="edit-name"
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
            />
          </div>

          {editTarget?.type === 'product' && (
            <div className="space-y-2">
              <Label htmlFor="edit-description">Descrição</Label>
              <Textarea
                id="edit-description"
                rows={2}
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="Aparece no cardápio que o agente manda pelo WhatsApp"
              />
            </div>
          )}

          {editTarget?.type !== 'group' && (
            <div className="space-y-2">
              <Label htmlFor="edit-price">
                {editTarget?.type === 'product' ? 'Preço base (R$)' : 'Preço extra (R$)'}
              </Label>
              <Input
                id="edit-price"
                type="number"
                step="0.01"
                min={0}
                value={form.price}
                onChange={(e) => set('price', e.target.value)}
              />
              {editTarget?.type === 'complement' && (
                <p className="text-xs text-muted-foreground">
                  Zero significa que o item não cobra nada a mais.
                </p>
              )}
            </div>
          )}

          {editTarget?.type === 'complement' && (
            <div className="space-y-2">
              <Label htmlFor="edit-category">Categoria do sabor</Label>
              <Select
                id="edit-category"
                value={form.categoryId}
                onChange={(e) => set('categoryId', e.target.value)}
              >
                <option value="">Não se aplica</option>
                {flavorCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
              <p className="text-xs text-muted-foreground">
                É por ela que o cardápio do WhatsApp sai agrupado. Para criar ou
                renomear categorias, use “Categorias de sabor” no topo da tela.
              </p>
            </div>
          )}

          {editTarget?.type === 'group' && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="edit-min">Mínimo de escolhas</Label>
                  <Input
                    id="edit-min"
                    type="number"
                    min={0}
                    value={form.minChoices}
                    onChange={(e) => set('minChoices', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edit-max">Máximo de escolhas</Label>
                  <Input
                    id="edit-max"
                    type="number"
                    min={1}
                    value={form.maxChoices}
                    onChange={(e) => set('maxChoices', e.target.value)}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="edit-required">Obrigatória</Label>
                  <p className="text-xs text-muted-foreground">
                    O agente só fecha o item depois de preencher esta escolha.
                  </p>
                </div>
                <Switch
                  id="edit-required"
                  checked={form.required}
                  onCheckedChange={(v) => set('required', v)}
                />
              </div>
              {erroDeEscolhas && (
                <p className="text-sm text-destructive">{erroDeEscolhas}</p>
              )}
            </>
          )}

          {editTarget?.type !== 'group' && (
            <div className="flex items-center justify-between">
              <Label htmlFor="edit-available">Disponível</Label>
              <Switch
                id="edit-available"
                checked={form.available}
                onCheckedChange={(v) => set('available', v)}
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="edit-sort">Ordem de exibição</Label>
            <Input
              id="edit-sort"
              type="number"
              min={0}
              value={form.sortOrder}
              onChange={(e) => set('sortOrder', e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Menor número aparece primeiro, no painel e no WhatsApp.
            </p>
          </div>

          <Button
            className="w-full"
            onClick={handleSave}
            disabled={loading || !form.name.trim() || !!erroDeEscolhas}
          >
            {loading ? 'Salvando...' : 'Salvar alterações'}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
};
