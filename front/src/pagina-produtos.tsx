/**
 * A tela de Produtos: a unica do painel que grava dados.
 *
 * E o CRUD do cardapio, que muda todo dia — os sabores disponiveis hoje.
 * Os dialogos e cartoes vem antes; a tela em si esta no fim do arquivo.
 */

import { Button } from '@/ui';
import { Plus, Tags, Pencil, Trash2, X, ChevronRight, FolderPlus, CheckCircle2, Search, XCircle, ListChecks, GripVertical } from 'lucide-react';
import { PageTitle, Page } from '@/comuns';
import { RefreshButton } from '@/comuns';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/ui';
import { useState, useEffect, useMemo } from 'react';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from '@/ui';
import { Input } from '@/ui';
import { Label } from '@/ui';
import { Switch } from '@/ui';
import { Textarea } from '@/ui';
import { useAsyncSubmit } from '@/dados';
import type { ProductInput, ComplementInput, ComplementCategory, GroupInput, GroupLibraryEntry, ComplementCategoryInput, CatalogEntity, Complement, ComplementGroup, Product } from '@/tipos';
import { Select } from '@/ui';
import { SortableList } from '@/comuns';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/ui';
import type { ReactNode } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/ui';
import { Badge } from '@/ui';
import { formatCurrency } from '@/formato';
import { cn } from '@/formato';
import { Skeleton } from '@/ui';
import { EmptyState, QueryError } from '@/comuns';
import { useProducts } from '@/dados';

// ---------------------------------------------------------------
// ProductsHeader
// ---------------------------------------------------------------

interface PropsProductsheader {
  onNewProduct: () => void;
  onManageCategories: () => void;
  onRefresh: () => unknown;
}

export const ProductsHeader = ({ onNewProduct, onManageCategories, onRefresh }: PropsProductsheader) => (
  <PageTitle
    title="Produtos"
    subtitle="Gerencie o cardápio e complementos"
    actions={
      // Três botões de largura normal nunca cabem numa faixa de 390px — "Novo
      // Produto" era o que estourava a tela. No celular viram duas linhas:
      // as ações secundárias dividindo uma faixa, a principal cheia embaixo.
      <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
        <div className="flex gap-2">
          <RefreshButton onRefresh={onRefresh} className="flex-1 sm:flex-none" />
          <Button
            variant="outline"
            onClick={onManageCategories}
            className="min-h-11 flex-1 sm:min-h-10 sm:flex-none"
          >
            <Tags className="mr-2 h-4 w-4" />
            <span className="hidden sm:inline">Categorias de item</span>
            <span className="sm:hidden">Categorias</span>
          </Button>
        </div>
        <Button onClick={onNewProduct} className="min-h-11 w-full sm:min-h-10 sm:w-auto">
          <Plus className="mr-2 h-4 w-4" />
          Novo Produto
        </Button>
      </div>
    }
  />
);

// ---------------------------------------------------------------
// DeleteConfirmDialog
// ---------------------------------------------------------------

interface PropsDeleteconfirmdialog {
  open: boolean;
  name: string;
  cascadeWarning?: boolean;
  /** Nuance do caso específico — ex.: excluir categoria não apaga sabor. */
  usageNote?: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export const DeleteConfirmDialog = ({ open, name, cascadeWarning, usageNote, onOpenChange, onConfirm }: PropsDeleteconfirmdialog) => (
  <AlertDialog open={open} onOpenChange={onOpenChange}>
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>Tem certeza que deseja excluir?</AlertDialogTitle>
        <AlertDialogDescription>
          {cascadeWarning
            ? <>Isso excluirá <strong>"{name}"</strong> e <strong>todos os itens/sabores dentro dela</strong>. Esta ação não pode ser desfeita.</>
            : <>O item <strong>"{name}"</strong> será removido permanentemente. Esta ação não pode ser desfeita.</>
          }
        </AlertDialogDescription>
        {usageNote && (
          <AlertDialogDescription className="text-muted-foreground">
            {usageNote}
          </AlertDialogDescription>
        )}
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>Cancelar</AlertDialogCancel>
        <AlertDialogAction onClick={onConfirm} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
          Excluir
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
);

// ---------------------------------------------------------------
// CreateProductDialog
// ---------------------------------------------------------------

interface PropsCreateproductdialog {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (data: ProductInput) => Promise<unknown>;
}

export const CreateProductDialog = ({ open, onOpenChange, onCreate }: PropsCreateproductdialog) => {
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

// ---------------------------------------------------------------
// CreateComplementDialog
// ---------------------------------------------------------------

interface PropsCreatecomplementdialog {
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
}: PropsCreatecomplementdialog) => {
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

// ---------------------------------------------------------------
// CreateGroupDialog
// ---------------------------------------------------------------

/** Valor da opção "criar uma lista nova" no select. */
const NOVA = '';

interface PropsCreategroupdialog {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  productId: string;
  productName: string;
  /** Listas que já existem, para o produto reaproveitar em vez de copiar. */
  library: GroupLibraryEntry[];
  /** Grupos que este produto já usa — não faz sentido oferecê-los de novo. */
  usedGroupIds: string[];
  /** O produto vai na rota (`POST /api/products/{id}/groups`), não no corpo. */
  onCreate: (productId: string, data: GroupInput) => Promise<unknown>;
}

export const CreateGroupDialog = ({
  open,
  onOpenChange,
  productId,
  productName,
  library,
  usedGroupIds,
  onCreate,
}: PropsCreategroupdialog) => {
  const [groupId, setGroupId] = useState(NOVA);
  const [name, setName] = useState('');
  const [min, setMin] = useState('0');
  const [max, setMax] = useState('3');
  const [required, setRequired] = useState(false);
  const { loading, run } = useAsyncSubmit();

  const disponiveis = library.filter((g) => !usedGroupIds.includes(g.id));
  const criandoNova = groupId === NOVA;
  const podeSalvar = criandoNova ? name.trim().length > 0 : true;

  const reset = () => {
    setGroupId(NOVA);
    setName('');
    setMin('0');
    setMax('3');
    setRequired(false);
  };

  const handleSubmit = () => {
    if (!podeSalvar || !productId) return;
    run(async () => {
      const minChoices = Number.parseInt(min, 10) || 0;
      const maxChoices = Math.max(Number.parseInt(max, 10) || 1, minChoices || 1);
      await onCreate(productId, {
        // Um ou outro, nunca os dois: o backend recusa o payload com ambos.
        ...(criandoNova ? { name: name.trim() } : { group_id: groupId }),
        min_choices: minChoices,
        max_choices: maxChoices,
        is_required: required,
      });
      reset();
      onOpenChange(false);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Grupo de opções para "{productName}"</DialogTitle>
          <DialogDescription>
            Uma lista de opções pode ser usada por vários produtos. Os mesmos sabores
            servem ao pote de 240ml e ao de 500ml — o que muda é quantos o cliente
            escolhe, e isso você define aqui.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {disponiveis.length > 0 && (
            <div className="space-y-2">
              <Label htmlFor="group-existing">Lista de opções</Label>
              <Select
                id="group-existing"
                value={groupId}
                onChange={(e) => setGroupId(e.target.value)}
              >
                <option value={NOVA}>Criar uma lista nova</option>
                {disponiveis.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name} ({g.complements.length} itens)
                  </option>
                ))}
              </Select>
              <p className="text-xs text-muted-foreground">
                Reaproveitar uma lista é o que faz "pistache acabou" valer para todos os
                produtos de uma vez.
              </p>
            </div>
          )}

          {criandoNova && (
            <div className="space-y-2">
              <Label htmlFor="group-name">Nome da lista</Label>
              <Input
                id="group-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ex.: Sabores, Coberturas"
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="group-min">Mín. escolhas</Label>
              <Input
                id="group-min"
                type="number"
                min={0}
                value={min}
                onChange={(e) => setMin(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="group-max">Máx. escolhas</Label>
              <Input
                id="group-max"
                type="number"
                min={1}
                value={max}
                onChange={(e) => setMax(e.target.value)}
              />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <Label htmlFor="group-required">Obrigatório</Label>
              <p className="text-xs text-muted-foreground">
                O agente só fecha o item depois de preencher este grupo.
              </p>
            </div>
            <Switch id="group-required" checked={required} onCheckedChange={setRequired} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !podeSalvar}>
            {loading ? 'Salvando...' : criandoNova ? 'Criar grupo' : 'Usar esta lista'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

// ---------------------------------------------------------------
// ComplementCategoriesDialog
// ---------------------------------------------------------------

interface PropsComplementcategoriesdialog {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: ComplementCategory[];
  /** Quantos sabores usam cada categoria — para avisar antes de excluir. */
  usageByCategory: Record<string, number>;
  onCreate: (data: ComplementCategoryInput) => Promise<unknown>;
  onRename: (id: string, data: Partial<ComplementCategoryInput>) => Promise<unknown>;
  onDelete: (id: string, name: string, usage: number) => void;
  onReorder: (ids: string[]) => void;
}

export const ComplementCategoriesDialog = ({
  open,
  onOpenChange,
  categories,
  usageByCategory,
  onCreate,
  onRename,
  onDelete,
  onReorder,
}: PropsComplementcategoriesdialog) => {
  const [novoNome, setNovoNome] = useState('');
  const [editandoId, setEditandoId] = useState<string | null>(null);
  const [nomeEditado, setNomeEditado] = useState('');
  const { loading, run } = useAsyncSubmit();

  const criar = () => {
    const nome = novoNome.trim();
    if (!nome) return;
    run(async () => {
      await onCreate({ name: nome, sort_order: categories.length + 1 });
      setNovoNome('');
    });
  };

  const salvarNome = (id: string) => {
    const nome = nomeEditado.trim();
    if (!nome) return;
    run(async () => {
      await onRename(id, { name: nome });
      setEditandoId(null);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* dvh, não vh: no Safari do iOS a barra de endereço muda de altura, e
          vh fixo cortava o rodapé do diálogo atrás dela. */}
      <DialogContent className="max-h-[85dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Categorias de complemento</DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted-foreground">
          Classificam um item em qualquer produto — “Sem lactose”, “Vegetariano”,
          “Picante”. Agrupam o cardápio que o agente manda pelo WhatsApp e são o
          que responde “tem opção sem lactose?”. Arraste para mudar a ordem.
        </p>

        <div className="rounded-md border border-border">
          {categories.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              Nenhuma categoria ainda.
            </p>
          )}
          <SortableList items={categories} onReorder={onReorder}>
            {(category, handle) => {
            const usos = usageByCategory[category.id] ?? 0;
            return (
              <div className="flex items-center gap-1 border-b border-border px-1 py-2 last:border-b-0 sm:gap-2 sm:px-3">
                {handle}
                {editandoId === category.id ? (
                  <>
                    <Input
                      value={nomeEditado}
                      onChange={(e) => setNomeEditado(e.target.value)}
                      aria-label={`Novo nome de ${category.name}`}
                      className="h-10 flex-1"
                      onKeyDown={(e) => e.key === 'Enter' && salvarNome(category.id)}
                    />
                    <Button size="sm" disabled={loading} onClick={() => salvarNome(category.id)}>
                      Salvar
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-10 w-10"
                      aria-label="Cancelar"
                      onClick={() => setEditandoId(null)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{category.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {usos === 0
                          ? 'nenhum item usa'
                          : `${usos} ${usos === 1 ? 'item usa' : 'itens usam'}`}
                      </p>
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-10 w-10"
                      aria-label={`Renomear ${category.name}`}
                      onClick={() => {
                        setEditandoId(category.id);
                        setNomeEditado(category.name);
                      }}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-10 w-10"
                      aria-label={`Excluir ${category.name}`}
                      onClick={() => onDelete(category.id, category.name, usos)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </>
                )}
              </div>
            );
            }}
          </SortableList>
        </div>

        <div className="space-y-2">
          <Label htmlFor="nova-categoria">Nova categoria</Label>
          <div className="flex gap-2">
            <Input
              id="nova-categoria"
              value={novoNome}
              onChange={(e) => setNovoNome(e.target.value)}
              placeholder="Ex.: Frutados"
              onKeyDown={(e) => e.key === 'Enter' && criar()}
            />
            <Button onClick={criar} disabled={loading || !novoNome.trim()}>
              <Plus className="mr-2 h-4 w-4" />
              Criar
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

// ---------------------------------------------------------------
// EditItemSheet
// ---------------------------------------------------------------

export type EditTarget =
  | { type: 'product'; item: Product }
  | { type: 'group'; item: ComplementGroup }
  | { type: 'complement'; item: Complement };

interface PropsEdititemsheet {
  editTarget: EditTarget | null;
  categories: ComplementCategory[];
  onClose: () => void;
  onSave: (entity: CatalogEntity, id: string, data: Record<string, unknown>) => Promise<unknown>;
}

const TITULOS: Record<EditTarget['type'], string> = {
  product: 'Editar produto',
  group: 'Editar grupo de opções',
  complement: 'Editar item',
};

/** Campos de todos os níveis num estado só — cada tipo usa os seus. */
interface Form {
  name: string;
  description: string;
  price: string;
  available: boolean;
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
    };
  }

  if (target.type === 'group') {
    const group = target.item;
    return {
      ...base,
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
    categoryId: complement.category_id ?? '',
  };
}

function numero(valor: string, minimo = 0): number {
  const parsed = Number.parseInt(valor, 10);
  return Number.isNaN(parsed) ? minimo : Math.max(minimo, parsed);
}

export const EditItemSheet = ({ editTarget, categories, onClose, onSave }: PropsEdititemsheet) => {
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
  // agente decide "falta escolher alguma coisa?" olhando esse mínimo.
  const erroDeEscolhas =
    editTarget?.type === 'group'
      ? max < min
        ? 'O máximo não pode ser menor que o mínimo.'
        : form.required && min < 1
          ? 'Grupo obrigatório precisa de no mínimo 1 escolha.'
          : null
      : null;

  const handleSave = () => {
    if (!editTarget) return;
    run(async () => {
      const data: Record<string, unknown> = { name: form.name.trim() };

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
        data.category_id = form.categoryId || null;
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
              <Label htmlFor="edit-category">Categoria do item</Label>
              <Select
                id="edit-category"
                value={form.categoryId}
                onChange={(e) => set('categoryId', e.target.value)}
              >
                <option value="">Não se aplica</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
              <p className="text-xs text-muted-foreground">
                É por ela que o cardápio do WhatsApp sai agrupado. Para criar ou
                renomear, use “Categorias” no topo da tela.
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

// ---------------------------------------------------------------
// GroupCard
// ---------------------------------------------------------------

interface PropsGroupcard {
  /** O grupo já traz seus complementos aninhados. */
  group: ComplementGroup;
  categories: ComplementCategory[];
  isSaving: boolean;
  /** Termo de busca ativo: com filtro, o grupo nasce aberto. */
  filtro?: string;
  /** Alça de arrasto do próprio grupo, vinda da lista de cima. */
  dragHandle?: ReactNode;
  /** Ids dos complementos marcados para edição em massa. */
  selecionados: Set<string>;
  onToggleSelecao: (id: string) => void;
  onSelecionarGrupo: (ids: string[], marcar: boolean) => void;
  onToggleComplement: (complement: Complement) => void;
  onEditComplement: (complement: Complement) => void;
  onDeleteComplement: (complement: Complement) => void;
  onReorderComplements: (ids: string[]) => void;
  onEditGroup: () => void;
  onDeleteGroup: () => void;
  onAddComplement: () => void;
}

/** Nome da categoria do complemento, ou undefined quando ele não tem uma. */
function categoryName(
  complement: Complement,
  categories: ComplementCategory[],
): string | undefined {
  return categories.find((c) => c.id === complement.category_id)?.name;
}

/** "escolhe 3" / "escolhe 1 a 2" — a regra que o agente segue na conversa. */
function regraDeEscolha(group: ComplementGroup): string {
  if (group.min_choices === group.max_choices) return `escolhe ${group.min_choices}`;
  return `escolhe ${group.min_choices} a ${group.max_choices}`;
}

export const GroupCard = ({
  group,
  categories,
  isSaving,
  filtro,
  dragHandle,
  selecionados,
  onToggleSelecao,
  onSelecionarGrupo,
  onToggleComplement,
  onEditComplement,
  onDeleteComplement,
  onReorderComplements,
  onEditGroup,
  onDeleteGroup,
  onAddComplement,
}: PropsGroupcard) => {
  const disponiveis = group.complements.filter((c) => c.is_available).length;
  const total = group.complements.length;
  const ids = group.complements.map((c) => c.id);
  const marcadosAqui = ids.filter((id) => selecionados.has(id)).length;
  const todosMarcados = total > 0 && marcadosAqui === total;

  // Caixa de marcar e alça de arrastar somem por padrão: com 31 sabores, dois
  // controles que servem só de vez em quando (selecionar em massa, reordenar)
  // sempre visíveis em CADA linha forçavam a quebra em duas linhas por item e
  // deixavam a lista pesada de rolar. Agora são um modo que se liga quando
  // precisa — o resto do tempo a linha é só nome, preço, disponibilidade e
  // editar/excluir.
  const [modoSelecionar, setModoSelecionar] = useState(false);
  const [modoReordenar, setModoReordenar] = useState(false);

  const alternarModoSelecionar = () => {
    // Saindo do modo: limpa o que estava marcado NESTE grupo, para a barra de
    // seleção em massa não ficar com itens marcados que o cliente não vê mais.
    if (modoSelecionar) onSelecionarGrupo(ids, false);
    setModoSelecionar((atual) => !atual);
  };

  // Arrastar com a busca ativa reordenaria uma lista PARCIAL: a posição
  // gravada seria a das linhas visíveis, não a real.
  const podeArrastar = !filtro && modoReordenar;

  return (
    <Card className="overflow-hidden">
      {/* <details> nativo: abre e fecha sem JavaScript e sem biblioteca, e o
          Safari do iOS já trata o toque no <summary> como botão. */}
      <details open={Boolean(filtro)} className="group/details">
        <summary
          className={cn(
            'flex cursor-pointer list-none items-center gap-2 px-2 py-3 sm:px-4 sm:gap-3',
            'hover:bg-muted/50 [&::-webkit-details-marker]:hidden',
          )}
        >
          {dragHandle}
          <ChevronRight
            className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open/details:rotate-90"
            aria-hidden
          />

          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold leading-tight">{group.name}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {/* A conta que importa no dia a dia: quantos estão no ar. */}
              <span className={cn(disponiveis === 0 && 'font-medium text-destructive')}>
                {disponiveis} de {total} disponíveis
              </span>
            </p>
          </div>

          {/* A regra de escolha ao lado do botão que a edita: é ela que decide
              quantas opções o agente pede antes de fechar o item. */}
          <Badge
            variant={group.is_required ? 'default' : 'secondary'}
            className="hidden shrink-0 sm:inline-flex"
          >
            {group.is_required ? 'Obrigatório' : 'Opcional'} · {regraDeEscolha(group)}
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 shrink-0 sm:h-9 sm:w-9"
            aria-label={`Editar regras de ${group.name}`}
            onClick={(e) => {
              // Dentro de <summary>: sem isto o clique abriria/fecharia o grupo.
              e.preventDefault();
              e.stopPropagation();
              onEditGroup();
            }}
          >
            <Pencil className="h-4 w-4" />
          </Button>
        </summary>

        {/* No celular o selo não cabe na linha do título; aqui ele reaparece. */}
        <p className="px-4 pb-2 text-xs text-muted-foreground sm:hidden">
          {group.is_required ? 'Obrigatório' : 'Opcional'} · {regraDeEscolha(group)}
        </p>

        {total > 0 && (
          // Liga/desliga a caixa de marcar e a alça de arrastar em cada linha —
          // ver o comentário em cima de `modoSelecionar`. "Reordenar" começa
          // desligado mesmo sem busca ativa: arrastar sem querer ao rolar a
          // lista era o jeito mais fácil de bagunçar a ordem dos 31 sabores.
          <div className="flex items-center gap-2 border-t border-border bg-muted/10 px-2 py-1.5 sm:px-4">
            <Button
              type="button"
              variant={modoSelecionar ? 'secondary' : 'ghost'}
              size="sm"
              className="h-8 gap-1.5 text-xs"
              onClick={alternarModoSelecionar}
            >
              <ListChecks className="h-3.5 w-3.5" />
              Selecionar
            </Button>
            <Button
              type="button"
              variant={modoReordenar ? 'secondary' : 'ghost'}
              size="sm"
              className="h-8 gap-1.5 text-xs"
              disabled={Boolean(filtro)}
              onClick={() => setModoReordenar((atual) => !atual)}
            >
              <GripVertical className="h-3.5 w-3.5" />
              Reordenar
            </Button>
          </div>
        )}

        <div className="border-t border-border">
          {total === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              Nenhum item neste grupo
            </p>
          ) : (
            <SortableList
              items={group.complements}
              onReorder={onReorderComplements}
              disabled={!podeArrastar}
            >
              {(complement, handle) => (
                <div
                  className={cn(
                    'flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border/60 px-2 py-2 sm:gap-x-3 sm:px-4',
                    !complement.is_available && 'bg-muted/30',
                  )}
                >
                  {/* Sem truncate/flex-1: um nome que não cabe ao lado do preço e
                      dos controles empurra os dois para a linha de baixo, em vez
                      de espremer o próprio nome até sumir. Nome curto continua
                      numa linha só; nome comprido só quebra as PALAVRAS se nem
                      sozinho couber nos 390px. */}
                  <div className="flex items-center gap-2">
                    {podeArrastar && handle}
                    {modoSelecionar && (
                      <input
                        type="checkbox"
                        checked={selecionados.has(complement.id)}
                        onChange={() => onToggleSelecao(complement.id)}
                        aria-label={`Selecionar ${complement.name}`}
                        className="h-5 w-5 shrink-0 cursor-pointer accent-[hsl(var(--primary))]"
                      />
                    )}
                    <span
                      className={cn(
                        'text-sm font-medium',
                        !complement.is_available && 'text-muted-foreground line-through',
                      )}
                    >
                      {complement.name}
                    </span>
                    {categoryName(complement, categories) && (
                      <Badge variant="secondary" className="shrink-0 font-normal">
                        {categoryName(complement, categories)}
                      </Badge>
                    )}
                  </div>

                  <span className="text-xs text-muted-foreground sm:text-sm">
                    {complement.extra_price > 0
                      ? formatCurrency(complement.extra_price)
                      : 'Incluso'}
                  </span>

                  {/* ml-auto cola os controles na direita, que é onde o polegar
                      alcança sem atravessar a tela. */}
                  <div className="ml-auto flex shrink-0 items-center gap-0.5">
                    <Switch
                      checked={complement.is_available}
                      aria-label={`Disponibilidade de ${complement.name}`}
                      onCheckedChange={() => onToggleComplement(complement)}
                      disabled={isSaving}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-11 w-11 sm:h-9 sm:w-9"
                      aria-label={`Editar ${complement.name}`}
                      onClick={() => onEditComplement(complement)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-11 w-11 sm:h-9 sm:w-9"
                      aria-label={`Excluir ${complement.name}`}
                      onClick={() => onDeleteComplement(complement)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              )}
            </SortableList>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-border bg-muted/20 px-4 py-3">
            {modoSelecionar && total > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="min-h-11 sm:min-h-9"
                onClick={() => onSelecionarGrupo(ids, !todosMarcados)}
              >
                {todosMarcados ? 'Desmarcar todos' : 'Selecionar todos'}
              </Button>
            )}
            <Button variant="outline" size="sm" className="min-h-11 sm:min-h-9" onClick={onAddComplement}>
              <Plus className="mr-2 h-4 w-4" />
              Adicionar item
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="min-h-11 text-destructive hover:text-destructive sm:min-h-9"
              onClick={onDeleteGroup}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {/* "Remover" e não "excluir": a lista é compartilhada e continua
                  existindo para os outros produtos que a usam. */}
              Remover deste produto
            </Button>
          </div>
        </div>
      </details>
    </Card>
  );
};

// ---------------------------------------------------------------
// ProductCard
// ---------------------------------------------------------------

/** O que o diálogo de exclusão precisa saber sobre o alvo. */
export interface DeleteTarget {
  entity: CatalogEntity;
  id: string;
  name: string;
  cascadeWarning?: boolean;
  usageNote?: string;
}

interface PropsProductcard {
  product: Product;
  catalog: ReturnType<typeof useProducts>;
  categories: ComplementCategory[];
  /** Alça de arrasto do produto; ausente enquanto há busca ativa. */
  dragHandle?: ReactNode;
  /** Termo de busca — com filtro, arrastar é desligado e os grupos abrem. */
  filtro: string;
  selecionados: Set<string>;
  onToggleSelecao: (id: string) => void;
  onSelecionarGrupo: (ids: string[], marcar: boolean) => void;
  onEdit: (target: EditTarget) => void;
  onDelete: (target: DeleteTarget) => void;
  onNewGroup: (product: { id: string; name: string }) => void;
  onNewComplement: (groupId: string) => void;
}

export const ProductCard = ({
  product,
  catalog,
  categories,
  dragHandle,
  filtro,
  selecionados,
  onToggleSelecao,
  onSelecionarGrupo,
  onEdit,
  onDelete,
  onNewGroup,
  onNewComplement,
}: PropsProductcard) => (
  <Card className={product.is_available ? undefined : 'opacity-70'}>
    {/* Nome e preço em cima, controles ao lado: numa faixa de 390px, nome +
        preço + interruptor + dois botões na mesma linha não cabem, e o título
        era o primeiro a ser cortado. */}
    <CardHeader className="pb-3">
      <div className="flex items-start justify-between gap-2">
        {dragHandle && <div className="pt-1">{dragHandle}</div>}
        <div className="min-w-0 flex-1">
          <CardTitle className="truncate text-lg sm:text-xl">{product.name}</CardTitle>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{formatCurrency(product.base_price)}</Badge>
            {!product.is_available && <Badge variant="outline">Indisponível</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Switch
            checked={product.is_available}
            aria-label={`Disponibilidade de ${product.name}`}
            onCheckedChange={() =>
              catalog.toggleAvailability('product', product.id, !product.is_available)
            }
            disabled={catalog.isSaving}
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 sm:h-9 sm:w-9"
            aria-label={`Editar ${product.name}`}
            onClick={() => onEdit({ type: 'product', item: product })}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-11 w-11 sm:h-9 sm:w-9"
            aria-label={`Excluir ${product.name}`}
            onClick={() =>
              onDelete({
                entity: 'product',
                id: product.id,
                name: product.name,
                cascadeWarning: product.groups.length > 0,
              })
            }
          >
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      </div>
    </CardHeader>

    <CardContent className="space-y-4">
      <SortableList
        items={product.groups}
        onReorder={(ids) => catalog.reorderGroups(product.id, ids)}
        disabled={Boolean(filtro)}
        className="space-y-4"
      >
        {(group, groupHandle) => (
          <GroupCard
            group={group}
            dragHandle={!filtro ? groupHandle : undefined}
            onReorderComplements={(ids) => catalog.reorderComplements(group.id, ids)}
            categories={categories}
            filtro={filtro}
            selecionados={selecionados}
            onToggleSelecao={onToggleSelecao}
            onSelecionarGrupo={onSelecionarGrupo}
            isSaving={catalog.isSaving}
            onToggleComplement={(complement) =>
              catalog.toggleAvailability(
                'complement',
                complement.id,
                !complement.is_available,
              )
            }
            onEditComplement={(complement) =>
              onEdit({ type: 'complement', item: complement })
            }
            onDeleteComplement={(complement) =>
              onDelete({
                entity: 'complement',
                id: complement.id,
                name: complement.name,
              })
            }
            onEditGroup={() => onEdit({ type: 'group', item: group })}
            onDeleteGroup={() =>
              onDelete({
                entity: 'group',
                id: group.id,
                name: group.name,
                // Sem cascata: os itens são da lista compartilhada e continuam
                // existindo para os outros produtos que a usam.
                usageNote: `Os ${group.complements.length} itens da lista continuam existindo — só deixam de valer para "${product.name}".`,
              })
            }
            // O id da LISTA, não o do vínculo: o complemento entra na lista
            // compartilhada e aparece em todo produto que a usa.
            onAddComplement={() => onNewComplement(group.group_id)}
          />
        )}
      </SortableList>

      <Button
        variant="outline"
        size="sm"
        className="min-h-11 w-full sm:min-h-9"
        onClick={() => onNewGroup({ id: product.id, name: product.name })}
      >
        <FolderPlus className="mr-2 h-4 w-4 shrink-0" />
        <span className="truncate">Novo grupo de opções</span>
      </Button>
    </CardContent>
  </Card>
);

// ---------------------------------------------------------------
// Produtos
// ---------------------------------------------------------------

const Produtos = () => {
  const catalog = useProducts();
  const { products, complementCategories, groupLibrary, isLoading, isError, error } = catalog;

  const [filtro, setFiltro] = useState('');
  // Edição em massa: ids dos complementos marcados. Um Set porque a operação
  // que mais roda é "está marcado?", uma vez por linha em cada render.
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  const [showNewProduct, setShowNewProduct] = useState(false);
  const [newGroupProduct, setNewGroupProduct] = useState<{ id: string; name: string } | null>(null);
  const [newComplementGroupId, setNewComplementGroupId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const [showCategories, setShowCategories] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  // Buscar sabor pelo nome. A lista de sabores é uma só e é longa (31 na Mi
  // Piace): sem busca, achar "pistache" no celular é rolagem. Produto e
  // categoria sem nenhum item correspondente somem enquanto o filtro está
  // ativo, para a tela mostrar só o que a busca encontrou.
  const termo = filtro.trim().toLowerCase();
  const visiveis = useMemo(() => {
    if (!termo) return products;
    return products
      .map((product) => ({
        ...product,
        groups: product.groups
          .map((group) => ({
            ...group,
            complements: group.complements.filter((c) =>
              c.name.toLowerCase().includes(termo),
            ),
          }))
          .filter((group) => group.complements.length > 0),
      }))
      .filter(
        (product) =>
          product.groups.length > 0 || product.name.toLowerCase().includes(termo),
      );
  }, [products, termo]);

  // Quantos sabores usam cada categoria — o diálogo avisa antes de excluir.
  const usoDasCategorias = useMemo(() => {
    const contagem: Record<string, number> = {};
    for (const product of products) {
      for (const group of product.groups) {
        for (const complement of group.complements) {
          const id = complement.category_id;
          if (id) contagem[id] = (contagem[id] ?? 0) + 1;
        }
      }
    }
    return contagem;
  }, [products]);

  const alternarSelecao = (id: string) =>
    setSelecionados((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(id)) proximo.delete(id);
      else proximo.add(id);
      return proximo;
    });

  const selecionarGrupo = (ids: string[], marcar: boolean) =>
    setSelecionados((atual) => {
      const proximo = new Set(atual);
      ids.forEach((id) => (marcar ? proximo.add(id) : proximo.delete(id)));
      return proximo;
    });

  // Liga ou desliga tudo que está marcado. Vai uma requisição por item: o
  // backend só tem PATCH por complemento, e para a dezena de sabores que o
  // lojista mexe por dia isso é mais simples do que inventar uma rota em lote.
  const aplicarEmMassa = (disponivel: boolean) => {
    selecionados.forEach((id) =>
      catalog.toggleAvailability('complement', id, disponivel),
    );
    setSelecionados(new Set());
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    catalog.deleteItem(deleteTarget.entity, deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <Page className="space-y-6">
      <ProductsHeader
        onNewProduct={() => setShowNewProduct(true)}
        onManageCategories={() => setShowCategories(true)}
        onRefresh={() => catalog.refetch()}
      />

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          placeholder="Buscar sabor ou produto..."
          aria-label="Buscar no cardápio"
          className="h-12 pl-9 sm:h-10"
        />
      </div>

      {isError ? (
        <QueryError
          error={error}
          onRetry={() => catalog.refetch()}
          title="Não foi possível carregar o cardápio"
        />
      ) : isLoading ? (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : visiveis.length === 0 ? (
        <EmptyState
          message={termo ? `Nada encontrado para "${filtro}".` : 'Nenhum produto cadastrado.'}
          hint={
            termo
              ? 'Tente outro termo ou limpe a busca.'
              : 'Comece criando um produto em "Novo Produto".'
          }
          className="border border-dashed rounded-lg py-12"
        />
      ) : (
        <SortableList
          items={visiveis}
          onReorder={catalog.reorderProducts}
          disabled={Boolean(termo)}
          className="space-y-6"
        >
          {(product, dragHandle) => (
            <ProductCard
              product={product}
              catalog={catalog}
              categories={complementCategories}
              dragHandle={!termo ? dragHandle : undefined}
              filtro={termo}
              selecionados={selecionados}
              onToggleSelecao={alternarSelecao}
              onSelecionarGrupo={selecionarGrupo}
              onEdit={setEditTarget}
              onDelete={setDeleteTarget}
              onNewGroup={setNewGroupProduct}
              onNewComplement={setNewComplementGroupId}
            />
          )}
        </SortableList>
      )}

      {/* Barra de edição em massa. Fixa no rodapé porque a seleção acontece
          rolando a lista: um botão no topo sairia da tela justo quando
          passasse a ser útil. */}
      {selecionados.size > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/95 px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] shadow-lg backdrop-blur-sm">
          <div className="container flex flex-wrap items-center gap-2 px-0">
            <span className="text-sm font-medium">
              {selecionados.size} selecionado{selecionados.size === 1 ? '' : 's'}
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button
                size="sm"
                className="min-h-11 gap-2 sm:min-h-9"
                disabled={catalog.isSaving}
                onClick={() => aplicarEmMassa(true)}
              >
                <CheckCircle2 className="h-4 w-4" />
                Ligar
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="min-h-11 gap-2 sm:min-h-9"
                disabled={catalog.isSaving}
                onClick={() => aplicarEmMassa(false)}
              >
                <XCircle className="h-4 w-4" />
                Desligar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="min-h-11 sm:min-h-9"
                onClick={() => setSelecionados(new Set())}
              >
                Limpar
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Diálogos */}
      <CreateProductDialog
        open={showNewProduct}
        onOpenChange={setShowNewProduct}
        onCreate={catalog.createProduct}
      />
      <CreateGroupDialog
        open={!!newGroupProduct}
        onOpenChange={(open) => !open && setNewGroupProduct(null)}
        productId={newGroupProduct?.id ?? ''}
        productName={newGroupProduct?.name ?? ''}
        library={groupLibrary}
        usedGroupIds={
          products
            .find((p) => p.id === newGroupProduct?.id)
            ?.groups.map((g) => g.group_id) ?? []
        }
        onCreate={catalog.createGroup}
      />
      <CreateComplementDialog
        open={!!newComplementGroupId}
        onOpenChange={(open) => !open && setNewComplementGroupId(null)}
        groupId={newComplementGroupId ?? ''}
        categories={complementCategories}
        onCreate={catalog.createComplement}
      />
      <ComplementCategoriesDialog
        open={showCategories}
        onOpenChange={setShowCategories}
        categories={complementCategories}
        usageByCategory={usoDasCategorias}
        onCreate={catalog.createComplementCategory}
        onRename={(id, data) => catalog.editItem('category', id, data)}
        onReorder={catalog.reorderCategories}
        onDelete={(id, name, usage) =>
          setDeleteTarget({
            entity: 'category',
            id,
            name,
            // Excluir categoria não apaga sabor: o vínculo vira nulo.
            usageNote:
              usage > 0
                ? `${usage} ${usage === 1 ? 'sabor perde' : 'sabores perdem'} o agrupamento, mas continuam no cardápio.`
                : undefined,
          })
        }
      />
      <EditItemSheet
        editTarget={editTarget}
        categories={complementCategories}
        onClose={() => setEditTarget(null)}
        onSave={catalog.editItem}
      />
      <DeleteConfirmDialog
        open={!!deleteTarget}
        name={deleteTarget?.name ?? ''}
        cascadeWarning={deleteTarget?.cascadeWarning}
        usageNote={deleteTarget?.usageNote}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </Page>
  );
};

export default Produtos;
