/**
 * Categorias de complemento: criar, renomear, reordenar e excluir.
 *
 * Classificam um complemento em qualquer produto: "Sem lactose" numa
 * gelateria, "Vegetariano" numa hamburgueria, "Salgadas" numa pizzaria. É por
 * elas que o cardápio do WhatsApp sai agrupado e que o agente responde "tem
 * opção sem lactose?".
 *
 * Esta tela faltava. O campo sempre existiu no cadastro do complemento, mas as
 * opções vinham do `seed.sql`: quem cadastrasse um produto novo encontrava um
 * select com duas opções de gelateria e nenhum lugar para criar as suas. Como
 * a lista é dado do lojista, ela precisa ser editável aqui — é o que permite
 * o mesmo sistema atender outro tipo de estabelecimento sem tocar em código.
 *
 * Excluir uma categoria NÃO apaga sabor nenhum: o vínculo é
 * `ON DELETE SET NULL`, então os sabores continuam no cardápio, apenas sem
 * agrupamento. O texto da tela diz isso, porque "excluir" costuma assustar.
 */

import { useState } from 'react';
import { Pencil, Plus, Trash2, X } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SortableList } from '@/components/common/SortableList';
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type { ComplementCategory, ComplementCategoryInput } from '@/types/catalog';

interface Props {
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
}: Props) => {
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
      <DialogContent className="max-h-[85vh] overflow-y-auto">
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
