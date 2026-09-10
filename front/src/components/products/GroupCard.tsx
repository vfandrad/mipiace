import { Plus, Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { formatCurrency } from '@/lib/format';
import type { Complement, ComplementGroup } from '@/types/catalog';

interface Props {
  /** O grupo já traz seus complementos aninhados. */
  group: ComplementGroup;
  isSaving: boolean;
  onToggleComplement: (complement: Complement) => void;
  onEditComplement: (complement: Complement) => void;
  onDeleteComplement: (complement: Complement) => void;
  onDeleteGroup: () => void;
  onAddComplement: () => void;
}

export const GroupCard = ({
  group,
  isSaving,
  onToggleComplement,
  onEditComplement,
  onDeleteComplement,
  onDeleteGroup,
  onAddComplement,
}: Props) => (
  <Card>
    <CardHeader>
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-lg">{group.name}</CardTitle>
          <Badge variant="outline">{group.is_required ? 'Obrigatório' : 'Opcional'}</Badge>
          <Badge variant="secondary">
            {group.min_choices}–{group.max_choices} escolhas
          </Badge>
        </div>
        <div className="flex gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={onAddComplement}
            title="Adicionar complemento"
            aria-label={`Adicionar complemento em ${group.name}`}
          >
            <Plus className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onDeleteGroup}
            title="Excluir categoria"
            aria-label={`Excluir categoria ${group.name}`}
          >
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      </div>
    </CardHeader>
    <CardContent className="p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nome</TableHead>
            <TableHead className="text-right">Preço extra</TableHead>
            <TableHead className="text-center">Disponível</TableHead>
            <TableHead className="text-right">Ações</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {group.complements.length === 0 ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center text-muted-foreground py-4">
                Sem complementos nesta categoria
              </TableCell>
            </TableRow>
          ) : (
            group.complements.map((complement) => (
              <TableRow key={complement.id}>
                <TableCell className="font-medium">{complement.name}</TableCell>
                <TableCell className="text-right">
                  {complement.extra_price > 0 ? formatCurrency(complement.extra_price) : 'Incluso'}
                </TableCell>
                <TableCell className="text-center">
                  <Switch
                    checked={complement.is_available}
                    aria-label={`Disponibilidade de ${complement.name}`}
                    onCheckedChange={() => onToggleComplement(complement)}
                    disabled={isSaving}
                  />
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Editar ${complement.name}`}
                      onClick={() => onEditComplement(complement)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Excluir ${complement.name}`}
                      onClick={() => onDeleteComplement(complement)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </CardContent>
  </Card>
);
