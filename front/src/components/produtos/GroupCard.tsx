/**
 * Categoria de um produto e seus complementos.
 *
 * Duas decisões que valem comentário, porque a versão anterior errava nas duas:
 *
 * 1. **Não é tabela.** Eram 4 colunas (nome, preço, disponível, ações) dentro
 *    de um `overflow-auto`. Numa tela de 390px isso virava rolagem horizontal
 *    dentro de cada card só para alcançar o interruptor — a ação mais usada da
 *    tela. Agora cada complemento é uma linha que se dobra: no celular o nome
 *    fica em cima e preço + controles embaixo; a partir de `sm` tudo cabe numa
 *    linha só.
 *
 * 2. **Começa fechada.** Cada um dos três tamanhos tem sua própria lista com os
 *    31 sabores, então a página abria com 93 linhas. Fechada, o cabeçalho já
 *    responde a pergunta do dia ("quantos sabores estão no ar?") e quem precisa
 *    mexer abre só a categoria que interessa.
 */

import { Plus, Pencil, Trash2, ChevronRight } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { formatCurrency } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Complement, ComplementGroup, FlavorCategory } from '@/types/catalog';

interface Props {
  /** O grupo já traz seus complementos aninhados. */
  group: ComplementGroup;
  flavorCategories: FlavorCategory[];
  isSaving: boolean;
  /** Termo de busca ativo: com filtro, a categoria nasce aberta. */
  filtro?: string;
  onToggleComplement: (complement: Complement) => void;
  onEditComplement: (complement: Complement) => void;
  onDeleteComplement: (complement: Complement) => void;
  onDeleteGroup: () => void;
  onAddComplement: () => void;
}

/** Nome da categoria do sabor, ou undefined quando o complemento não é sabor. */
function categoryName(
  complement: Complement,
  categories: FlavorCategory[],
): string | undefined {
  return categories.find((c) => c.id === complement.flavor_category_id)?.name;
}

export const GroupCard = ({
  group,
  flavorCategories,
  isSaving,
  filtro,
  onToggleComplement,
  onEditComplement,
  onDeleteComplement,
  onDeleteGroup,
  onAddComplement,
}: Props) => {
  const disponiveis = group.complements.filter((c) => c.is_available).length;
  const total = group.complements.length;

  return (
    <Card className="overflow-hidden">
      {/* <details> nativo: abre e fecha sem JavaScript e sem biblioteca, e o
          Safari do iOS já trata o toque no <summary> como botão. */}
      <details open={Boolean(filtro)} className="group/details">
        <summary
          className={cn(
            'flex cursor-pointer list-none items-center gap-3 px-4 py-3',
            'hover:bg-muted/50 [&::-webkit-details-marker]:hidden',
          )}
        >
          <ChevronRight
            className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open/details:rotate-90"
            aria-hidden
          />

          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold leading-tight">{group.name}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {/* A conta que importa no dia a dia: quantos sabores estão no ar. */}
              <span className={cn(disponiveis === 0 && 'font-medium text-destructive')}>
                {disponiveis} de {total} disponíveis
              </span>
              {' · '}
              {group.is_required ? 'Obrigatório' : 'Opcional'}
              {' · '}
              escolhe {group.min_choices === group.max_choices
                ? group.min_choices
                : `${group.min_choices}–${group.max_choices}`}
            </p>
          </div>
        </summary>

        <div className="border-t border-border">
          {total === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              Sem complementos nesta categoria
            </p>
          ) : (
            <ul>
              {group.complements.map((complement) => (
                <li
                  key={complement.id}
                  className={cn(
                    'flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/60 px-4 py-2 last:border-b-0',
                    !complement.is_available && 'bg-muted/30',
                  )}
                >
                  {/* basis-full no celular: o nome ocupa a primeira linha
                      inteira e os controles descem para a segunda, em vez de
                      espremerem tudo numa faixa de 390px. */}
                  <div className="flex min-w-0 basis-full items-center gap-2 sm:flex-1 sm:basis-auto">
                    <span
                      className={cn(
                        'truncate text-sm font-medium',
                        !complement.is_available && 'text-muted-foreground line-through',
                      )}
                    >
                      {complement.name}
                    </span>
                    {categoryName(complement, flavorCategories) && (
                      <Badge variant="secondary" className="shrink-0 font-normal">
                        {categoryName(complement, flavorCategories)}
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
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap gap-2 border-t border-border bg-muted/20 px-4 py-3">
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
              Excluir categoria
            </Button>
          </div>
        </div>
      </details>
    </Card>
  );
};
