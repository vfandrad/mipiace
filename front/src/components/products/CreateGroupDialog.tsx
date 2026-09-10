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
import { Switch } from '@/components/ui/switch';
import { useAsyncSubmit } from '@/hooks/use-async-submit';
import type { GroupInput } from '@/types/catalog';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  productId: string;
  productName: string;
  /** O produto vai na rota (`POST /api/products/{id}/groups`), não no corpo. */
  onCreate: (productId: string, data: GroupInput) => Promise<unknown>;
}

export const CreateGroupDialog = ({
  open,
  onOpenChange,
  productId,
  productName,
  onCreate,
}: Props) => {
  const [name, setName] = useState('');
  const [min, setMin] = useState('0');
  const [max, setMax] = useState('3');
  const [required, setRequired] = useState(false);
  const { loading, run } = useAsyncSubmit();

  const reset = () => {
    setName('');
    setMin('0');
    setMax('3');
    setRequired(false);
  };

  const handleSubmit = () => {
    if (!name.trim() || !productId) return;
    run(async () => {
      const minChoices = Number.parseInt(min, 10) || 0;
      const maxChoices = Math.max(Number.parseInt(max, 10) || 1, minChoices || 1);
      await onCreate(productId, {
        name: name.trim(),
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
          <DialogTitle>Nova categoria para "{productName}"</DialogTitle>
          <DialogDescription>
            A categoria pertence só a este produto. Ex.: os "Sabores" do Pote 500ml são
            independentes dos "Sabores" do Pote 240ml.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="group-name">Nome</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Sabores, Coberturas"
            />
          </div>
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
                O agente só fecha o item depois de preencher esta categoria.
              </p>
            </div>
            <Switch id="group-required" checked={required} onCheckedChange={setRequired} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !name.trim()}>
            {loading ? 'Criando...' : 'Criar categoria'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
