import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import type { GroupInput, GroupLibraryEntry } from '@/types/catalog';

/** Valor da opção "criar uma lista nova" no select. */
const NOVA = '';

interface Props {
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
}: Props) => {
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
