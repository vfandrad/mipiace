/**
 * Grupo de opções de um produto e os complementos dentro dele.
 *
 * Decisões que valem comentário, porque a versão anterior errava nelas:
 *
 * 1. **Não é tabela.** Eram 4 colunas (nome, preço, disponível, ações) dentro
 *    de um `overflow-auto`. Numa tela de 390px isso virava rolagem horizontal
 *    dentro de cada card só para alcançar o interruptor — a ação mais usada da
 *    tela. Agora cada complemento é uma linha que se dobra: no celular o nome
 *    fica em cima e preço + controles embaixo; a partir de `sm` tudo cabe numa
 *    linha só.
 *
 * 2. **Começa fechado.** Cada um dos três tamanhos tem sua própria lista com os
 *    31 sabores, então a página abria com 93 linhas. Fechado, o cabeçalho já
 *    responde a pergunta do dia ("quantos estão no ar?") e quem precisa mexer
 *    abre só o grupo que interessa.
 *
 * 3. **A regra de escolha fica visível e editável no cabeçalho.** "escolhe 3"
 *    é o que faz o agente pedir três opções antes de fechar o item; estava em
 *    letra miúda e o botão que a edita ficava escondido no rodapé do grupo —
 *    na prática não dava para trocar "escolha 3" por "escolha 1 a 2".
 */

import type { ReactNode } from 'react';
import { Plus, Pencil, Trash2, ChevronRight } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { SortableList } from '@/components/common/SortableList';
import { formatCurrency } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Complement, ComplementCategory, ComplementGroup } from '@/types/catalog';

interface Props {
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
}: Props) => {
  const disponiveis = group.complements.filter((c) => c.is_available).length;
  const total = group.complements.length;
  const ids = group.complements.map((c) => c.id);
  const marcadosAqui = ids.filter((id) => selecionados.has(id)).length;
  const todosMarcados = total > 0 && marcadosAqui === total;
  // Arrastar com a busca ativa reordenaria uma lista PARCIAL: a posição
  // gravada seria a das linhas visíveis, não a real.
  const podeArrastar = !filtro;

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
                  {/* basis-full no celular: o nome ocupa a primeira linha
                      inteira e os controles descem para a segunda, em vez de
                      espremerem tudo numa faixa de 390px. */}
                  <div className="flex min-w-0 basis-full items-center gap-2 sm:flex-1 sm:basis-auto">
                    {podeArrastar && handle}
                    <input
                      type="checkbox"
                      checked={selecionados.has(complement.id)}
                      onChange={() => onToggleSelecao(complement.id)}
                      aria-label={`Selecionar ${complement.name}`}
                      className="h-5 w-5 shrink-0 cursor-pointer accent-[hsl(var(--primary))]"
                    />
                    <span
                      className={cn(
                        'truncate text-sm font-medium',
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
            {total > 0 && (
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
              Excluir grupo
            </Button>
          </div>
        </div>
      </details>
    </Card>
  );
};
