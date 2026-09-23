/**
 * Categorias de sabor: criar, renomear, reordenar e excluir.
 *
 * Esta tela faltava. O cadastro do sabor sempre teve o campo "categoria do
 * sabor", mas as opções vinham do `seed.sql`: quem cadastrasse um produto novo
 * encontrava um select com duas opções de gelateria e nenhum lugar para criar
 * as suas. Como a lista é dado do lojista — "Sem lactose" numa sorveteria,
 * outra coisa em outra loja —, ela precisa ser editável aqui.
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
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type { FlavorCategory, FlavorCategoryInput } from '@/types/catalog';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: FlavorCategory[];
  /** Quantos sabores usam cada categoria — para avisar antes de excluir. */
  usageByCategory: Record<string, number>;
  onCreate: (data: FlavorCategoryInput) => Promise<unknown>;
  onRename: (id: string, data: Partial<FlavorCategoryInput>) => Promise<unknown>;
  onDelete: (id: string, name: string, usage: number) => void;
}

export const FlavorCategoriesDialog = ({
  open,
  onOpenChange,
  categories,
  usageByCategory,
  onCreate,
  onRename,
  onDelete,
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
          <DialogTitle>Categorias de sabor</DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted-foreground">
          Agrupam os sabores no cardápio que o agente manda pelo WhatsApp, e são
          o que responde “tem sabor sem lactose?”.
        </p>

        <ul className="divide-y divide-border rounded-md border border-border">
          {categories.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              Nenhuma categoria ainda.
            </li>
          )}
          {categories.map((category) => {
            const usos = usageByCategory[category.id] ?? 0;
            return (
              <li key={category.id} className="flex items-center gap-2 px-3 py-2">
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
                          ? 'nenhum sabor usa'
                          : `${usos} ${usos === 1 ? 'sabor usa' : 'sabores usam'}`}
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
              </li>
            );
          })}
        </ul>

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
