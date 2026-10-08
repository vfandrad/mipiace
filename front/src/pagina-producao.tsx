/**
 * A tela de Producao: o Kanban dos pedidos.
 *
 * So le e muda o status do pedido; nao edita nada do cardapio.
 */

import type { Order, OrderCreateInput, OrderStatus, Product } from '@/tipos';
import { ORDER_STATUS_INFO, nextOrderStatus } from '@/formato';
import { cn } from '@/formato';
import { useMemo, useState } from 'react';
import { Check, ChefHat, Clock, Copy, MapPin, Store, Truck, XCircle, Eye, EyeOff, Printer, ClipboardPlus, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/ui';
import { PaymentBadge } from '@/ui';
import { Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription } from '@/ui';
import { Input, Label, Select, Textarea } from '@/ui';
import { formatCurrency, formatPhone, formatTime, minutesSince } from '@/formato';
import { formatAddress } from '@/formato';
import { toast } from 'sonner';
import { Page, PageTitle } from '@/comuns';
import { QueryError } from '@/comuns';
import { Skeleton } from '@/ui';
import { useOrders, useProducts, useAsyncSubmit } from '@/dados';
import { RefreshButton } from '@/comuns';
import { printOrder, PrinterError } from '@/impressora';
import { PRINTER_IP } from '@/api';

// ---------------------------------------------------------------
// KanbanColumn
// ---------------------------------------------------------------

interface KanbanColumnProps {
  status: OrderStatus;
  orders: Order[];
  onStatusChange: (orderId: string, newStatus: OrderStatus) => void;
}

export function KanbanColumn({ status, orders, onStatusChange }: KanbanColumnProps) {

  return (
    <div className="kanban-column flex flex-col">
      <div className={cn('pb-3 mb-4 border-b-2', ORDER_STATUS_INFO[status].border)}>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-foreground">{ORDER_STATUS_INFO[status].plural}</h3>
          <span className="flex items-center justify-center h-6 w-6 rounded-full bg-card text-sm font-medium shadow-sm">
            {orders.length}
          </span>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto scrollbar-thin pr-1">
        {orders.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
            Nenhum pedido
          </div>
        ) : (
          orders.map((order) => (
            <OrderCard key={order.id} order={order} onStatusChange={onStatusChange} />
          ))
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------
// OrderCard
// ---------------------------------------------------------------

interface OrderCardProps {
  order: Order;
  onStatusChange: (orderId: string, newStatus: OrderStatus) => void;
}

const ACTION_CONFIG: Partial<
  Record<OrderStatus, { label: string; icon: React.ReactNode; className: string }>
> = {
  preparando: {
    label: 'Iniciar preparo',
    icon: <ChefHat className="h-4 w-4" />,
    className: 'action-btn-warning',
  },
  entrega: {
    label: 'Saiu p/ entrega',
    icon: <Truck className="h-4 w-4" />,
    className: 'action-btn-success',
  },
  finalizado: {
    label: 'Finalizar',
    icon: <Check className="h-4 w-4" />,
    className: 'action-btn-secondary',
  },
};

export function OrderCard({ order, onStatusChange }: OrderCardProps) {
  const [copied, setCopied] = useState(false);
  const minutesAgo = minutesSince(order.created_at);
  const isOpen = order.status !== 'finalizado' && order.status !== 'cancelado';
  const isUrgent = minutesAgo > 15 && isOpen;
  const nextStatus = nextOrderStatus(order.status);
  const action = nextStatus ? ACTION_CONFIG[nextStatus] : null;
  const address = formatAddress(order);
  const pixCode = order.payment_status === 'pendente' ? order.payment?.qr_code : null;
  const [printing, setPrinting] = useState(false);

  const handlePrint = async () => {
    setPrinting(true);
    try {
      await printOrder(order);
      toast.success('Ficha enviada pra impressora');
    } catch (error) {
      toast.error('Não consegui imprimir a ficha', {
        description: error instanceof PrinterError ? error.message : undefined,
      });
    } finally {
      setPrinting(false);
    }
  };

  const copyPix = async () => {
    if (!pixCode) return;
    try {
      await navigator.clipboard.writeText(pixCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Sem clipboard (http, permissão negada): o código segue visível na tela.
      setCopied(false);
    }
  };

  return (
    <div
      className={cn(
        'order-card',
        order.status === 'novo' && 'animate-pulse-subtle border-status-new/30',
        isUrgent && 'border-destructive/50',
        order.status === 'cancelado' && 'opacity-70',
      )}
    >
      {/* Código do pedido + horário */}
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-xs font-semibold text-muted-foreground">
          {order.code || '—'}
        </span>
        <div className="flex items-center gap-1 text-sm text-muted-foreground shrink-0">
          <Clock className="h-3.5 w-3.5" />
          <span>{formatTime(order.created_at)}</span>
          <span className={cn('text-xs', isUrgent && 'text-destructive font-medium')}>
            ({minutesAgo}min)
          </span>
        </div>
      </div>

      {/* Cliente */}
      <div className="mb-2">
        <p className="font-semibold text-foreground truncate">
          {order.customer_name || 'Cliente sem nome'}
        </p>
        {order.customer_phone && (
          <p className="text-xs text-muted-foreground">{formatPhone(order.customer_phone)}</p>
        )}
      </div>

      {/* Pagamento */}
      {/* Cartão/dinheiro na entrega não têm QR code: sem o selo aqui, um
          pedido assim fica indistinguível de um Pix morto na tela do balcão
          (os dois mostram só "Pendente"). */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <PaymentBadge status={order.payment_status} />
        {order.payment?.method === 'cartao' && (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-secondary text-secondary-foreground">
            💳 Cartão na entrega
          </span>
        )}
        {order.payment?.method === 'dinheiro' && (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-secondary text-secondary-foreground">
            💵 Dinheiro na entrega
          </span>
        )}
      </div>

      {/* Endereço de entrega */}
      {/* Retirada precisa estar visível no card: é a diferença entre despachar
          o pedido e deixá-lo no balcão esperando o cliente. Sem isso, o Kanban
          mostrava só a ausência de endereço, que é fácil confundir com dado
          faltando. */}
      {order.fulfillment_type === 'retirada' && (
        <div className="flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--status-production))]">
          <Store className="h-3.5 w-3.5 shrink-0" />
          <span>Retirada na loja</span>
        </div>
      )}

      {address && (
        <div className="flex items-start gap-1.5 text-sm text-muted-foreground mb-3">
          <MapPin className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>{address}</span>
        </div>
      )}

      {/* Itens */}
      <div className="space-y-2 mb-3">
        {order.items.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">Pedido sem itens.</p>
        ) : (
          order.items.map((item) => (
            <div key={item.id} className="text-sm">
              <div className="flex justify-between gap-2">
                <span className="font-medium">
                  {item.quantity}x {item.product_name_snapshot}
                </span>
                <span className="text-muted-foreground shrink-0">
                  {formatCurrency(item.line_total)}
                </span>
              </div>
              {item.details && (
                <p className="text-muted-foreground text-xs italic mt-0.5">{item.details}</p>
              )}
              {item.complements.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {item.complements.map((complement, index) => (
                    <span
                      key={complement.id ?? `${item.id}-${index}`}
                      className="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-secondary text-secondary-foreground"
                    >
                      {complement.complement_name_snapshot}
                      {complement.extra_price_snapshot > 0 &&
                        ` +${formatCurrency(complement.extra_price_snapshot)}`}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {order.notes && (
        <p className="text-xs bg-secondary/60 rounded p-2 mb-3">
          <span className="font-medium">Obs.: </span>
          {order.notes}
        </p>
      )}

      {/* Totais */}
      <div className="border-t border-border pt-3 space-y-1">
        {order.delivery_fee > 0 && (
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>Subtotal / entrega</span>
            <span>
              {formatCurrency(order.subtotal)} + {formatCurrency(order.delivery_fee)}
            </span>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="font-medium">Total</span>
          <span className="text-lg font-semibold">{formatCurrency(order.total)}</span>
        </div>
      </div>

      {/* Pix pendente: o balcão consegue reenviar o copia-e-cola ao cliente */}
      {pixCode && (
        <div className="mt-3 rounded-lg border border-status-production/40 bg-status-production-bg p-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-status-production">Pix aguardando</span>
            <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs" onClick={copyPix}>
              <Copy className="h-3 w-3" />
              {copied ? 'Copiado!' : 'Copiar código'}
            </Button>
          </div>
          <p className="mt-1 font-mono text-[10px] leading-tight text-muted-foreground break-all line-clamp-2">
            {pixCode}
          </p>
        </div>
      )}

      {/* Ações */}
      {isOpen && (
        <div className="mt-3 flex gap-2">
          {nextStatus && action && (
            <Button
              onClick={() => onStatusChange(order.id, nextStatus)}
              className={cn('flex-1 gap-2', action.className)}
              size="sm"
            >
              {action.icon}
              {action.label}
            </Button>
          )}
          {PRINTER_IP && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handlePrint}
              disabled={printing}
              title="Imprimir ficha"
              aria-label="Imprimir ficha do pedido"
            >
              <Printer className="h-4 w-4" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => onStatusChange(order.id, 'cancelado')}
            title="Cancelar pedido"
            aria-label="Cancelar pedido"
          >
            <XCircle className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------
// CreateManualOrderDialog
// ---------------------------------------------------------------
//
// Fallback para quando o agente de IA cai: o lojista monta o pedido pelo
// mesmo cardápio de hoje, à mão, sem depender do WhatsApp estar respondendo.
// Entra direto em "preparando" — quem digita já sabe se cobrou ou não.

type Grupo = Product['groups'][number];

interface DraftItem {
  key: string;
  product: Product;
  quantity: number;
  complementIds: string[];
}

function grupoSatisfeito(group: Grupo, complementIds: string[]): boolean {
  const escolhidos = complementIds.filter((id) => group.complements.some((c) => c.id === id));
  return escolhidos.length >= group.min_choices;
}

interface PropsCreatemanualorderdialog {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (data: OrderCreateInput) => Promise<unknown>;
}

function CreateManualOrderDialog({ open, onOpenChange, onCreate }: PropsCreatemanualorderdialog) {
  const { products } = useProducts();
  const disponiveis = useMemo(() => products.filter((p) => p.is_available), [products]);

  const [items, setItems] = useState<DraftItem[]>([]);
  const [draftProductId, setDraftProductId] = useState('');
  const [draftQuantity, setDraftQuantity] = useState(1);
  const [draftComplementIds, setDraftComplementIds] = useState<string[]>([]);

  const [customerName, setCustomerName] = useState('');
  const [phone, setPhone] = useState('');
  const [fulfillment, setFulfillment] = useState<'entrega' | 'retirada'>('retirada');
  const [rua, setRua] = useState('');
  const [numero, setNumero] = useState('');
  const [bairro, setBairro] = useState('');
  const [complemento, setComplemento] = useState('');
  const [paymentStatus, setPaymentStatus] = useState<'pago' | 'pendente'>('pago');
  const [notes, setNotes] = useState('');

  const { loading, run } = useAsyncSubmit();

  const draftProduct = disponiveis.find((p) => p.id === draftProductId) ?? null;

  const resetDraftItem = () => {
    setDraftProductId('');
    setDraftQuantity(1);
    setDraftComplementIds([]);
  };

  const resetAll = () => {
    setItems([]);
    resetDraftItem();
    setCustomerName('');
    setPhone('');
    setFulfillment('retirada');
    setRua('');
    setNumero('');
    setBairro('');
    setComplemento('');
    setPaymentStatus('pago');
    setNotes('');
  };

  const toggleComplement = (complementId: string, group: Grupo) => {
    setDraftComplementIds((atual) => {
      const foraDoGrupo = atual.filter((id) => !group.complements.some((c) => c.id === id));
      if (!complementId) return foraDoGrupo;
      if (group.max_choices === 1) return [...foraDoGrupo, complementId];
      const jaEscolhidos = atual.filter((id) => group.complements.some((c) => c.id === id));
      if (jaEscolhidos.includes(complementId)) {
        return [...foraDoGrupo, ...jaEscolhidos.filter((id) => id !== complementId)];
      }
      if (jaEscolhidos.length >= group.max_choices) return atual; // grupo cheio
      return [...foraDoGrupo, ...jaEscolhidos, complementId];
    });
  };

  const draftValido =
    draftProduct !== null &&
    draftProduct.groups.every((group) =>
      group.min_choices > 0 ? grupoSatisfeito(group, draftComplementIds) : true,
    );

  const addItem = () => {
    if (!draftProduct || !draftValido) return;
    setItems((atual) => [
      ...atual,
      {
        key: `${draftProduct.id}-${Date.now()}`,
        product: draftProduct,
        quantity: draftQuantity,
        complementIds: draftComplementIds,
      },
    ]);
    resetDraftItem();
  };

  const removeItem = (key: string) => {
    setItems((atual) => atual.filter((item) => item.key !== key));
  };

  const total = items.reduce((soma, item) => {
    const extras = item.complementIds.reduce((s, id) => {
      const comp = item.product.groups.flatMap((g) => g.complements).find((c) => c.id === id);
      return s + (comp?.extra_price ?? 0);
    }, 0);
    return soma + (item.product.base_price + extras) * item.quantity;
  }, 0);

  const enderecoCompleto = rua.trim() !== '' && numero.trim() !== '' && bairro.trim() !== '';
  const podeSubmeter =
    items.length > 0 && phone.trim() !== '' && (fulfillment === 'retirada' || enderecoCompleto);

  const handleSubmit = () => {
    if (!podeSubmeter) return;
    run(async () => {
      await onCreate({
        items: items.map((item) => ({
          product_id: item.product.id,
          quantity: item.quantity,
          complement_ids: item.complementIds,
        })),
        customer_name: customerName.trim() || null,
        phone: phone.trim(),
        fulfillment_type: fulfillment,
        address:
          fulfillment === 'entrega'
            ? {
                rua: rua.trim(),
                numero: numero.trim(),
                bairro: bairro.trim(),
                complemento: complemento.trim() || null,
              }
            : null,
        payment_status: paymentStatus,
        notes: notes.trim() || null,
      });
      resetAll();
      onOpenChange(false);
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) resetAll();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Registrar pedido manualmente</DialogTitle>
          <DialogDescription>
            Fallback para quando o agente de IA está fora do ar — monta o pedido pelo cardápio de
            hoje, igual o cliente veria no WhatsApp.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {items.length > 0 && (
            <div className="space-y-2 rounded-md border p-2">
              {items.map((item) => (
                <div key={item.key} className="flex items-start justify-between gap-2 text-sm">
                  <div>
                    <p className="font-medium">
                      {item.quantity}x {item.product.name}
                    </p>
                    {item.complementIds.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        {item.product.groups
                          .flatMap((g) => g.complements)
                          .filter((c) => item.complementIds.includes(c.id))
                          .map((c) => c.name)
                          .join(', ')}
                      </p>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={() => removeItem(item.key)}
                    aria-label="Remover item"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="space-y-2 rounded-md border border-dashed p-3">
            <Label>Produto</Label>
            <Select
              value={draftProductId}
              onChange={(e) => {
                setDraftProductId(e.target.value);
                setDraftComplementIds([]);
              }}
            >
              <option value="">Selecione um produto</option>
              {disponiveis.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name} — {formatCurrency(product.base_price)}
                </option>
              ))}
            </Select>

            {draftProduct?.groups.map((group) => (
              <div key={group.id} className="space-y-1">
                <Label className="text-xs text-muted-foreground">
                  {group.name}
                  {group.min_choices > 0
                    ? ` (escolha ${
                        group.min_choices === group.max_choices
                          ? group.min_choices
                          : `${group.min_choices} a ${group.max_choices}`
                      })`
                    : ' (opcional)'}
                </Label>
                {group.max_choices === 1 ? (
                  <Select
                    value={
                      draftComplementIds.find((id) => group.complements.some((c) => c.id === id)) ?? ''
                    }
                    onChange={(e) => toggleComplement(e.target.value, group)}
                  >
                    <option value="">Selecione</option>
                    {group.complements
                      .filter((c) => c.is_available)
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                          {c.extra_price > 0 ? ` (+${formatCurrency(c.extra_price)})` : ''}
                        </option>
                      ))}
                  </Select>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {group.complements
                      .filter((c) => c.is_available)
                      .map((c) => {
                        const ativo = draftComplementIds.includes(c.id);
                        return (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => toggleComplement(c.id, group)}
                            className={cn(
                              'rounded-full border px-2.5 py-1 text-xs',
                              ativo
                                ? 'border-primary bg-primary/10 text-primary'
                                : 'border-input text-muted-foreground',
                            )}
                          >
                            {c.name}
                          </button>
                        );
                      })}
                  </div>
                )}
              </div>
            ))}

            <div className="flex items-end gap-2">
              <div className="flex-1 space-y-1">
                <Label className="text-xs text-muted-foreground">Quantidade</Label>
                <Input
                  type="number"
                  min={1}
                  value={draftQuantity}
                  onChange={(e) =>
                    setDraftQuantity(Math.max(1, Number.parseInt(e.target.value, 10) || 1))
                  }
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                disabled={!draftProduct || !draftValido}
                onClick={addItem}
                className="gap-1"
              >
                <Plus className="h-4 w-4" />
                Adicionar
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label>Nome (opcional)</Label>
              <Input
                value={customerName}
                onChange={(e) => setCustomerName(e.target.value)}
                placeholder="Nome do cliente"
              />
            </div>
            <div className="space-y-1">
              <Label>Telefone</Label>
              <Input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="(11) 99999-9999"
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label>Entrega ou retirada</Label>
            <Select
              value={fulfillment}
              onChange={(e) => setFulfillment(e.target.value as 'entrega' | 'retirada')}
            >
              <option value="retirada">Retirada na loja</option>
              <option value="entrega">Entrega</option>
            </Select>
          </div>

          {fulfillment === 'entrega' && (
            <div className="grid grid-cols-2 gap-2">
              <Input
                value={rua}
                onChange={(e) => setRua(e.target.value)}
                placeholder="Rua"
                className="col-span-2"
              />
              <Input value={numero} onChange={(e) => setNumero(e.target.value)} placeholder="Número" />
              <Input value={bairro} onChange={(e) => setBairro(e.target.value)} placeholder="Bairro" />
              <Input
                value={complemento}
                onChange={(e) => setComplemento(e.target.value)}
                placeholder="Complemento (opcional)"
                className="col-span-2"
              />
            </div>
          )}

          <div className="space-y-1">
            <Label>Pagamento</Label>
            <Select
              value={paymentStatus}
              onChange={(e) => setPaymentStatus(e.target.value as 'pago' | 'pendente')}
            >
              <option value="pago">Já pago (dinheiro, cartão...)</option>
              <option value="pendente">Cobrar na entrega/retirada</option>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>Observações (opcional)</Label>
            <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          {items.length > 0 && (
            <div className="flex items-center justify-between border-t pt-2 text-sm font-medium">
              <span>Total</span>
              <span>{formatCurrency(total)}</span>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !podeSubmeter}>
            {loading ? 'Registrando...' : 'Registrar pedido'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------
// Producao
// ---------------------------------------------------------------

// "novo" (pix pendente) fica de fora: o pedido só entra no quadro quando o
// Pix é confirmado — é o próprio backend que move o pedido para "preparando"
// no momento em que o pagamento cai (ver services/orders.py::apply_payment_result).
const KANBAN_STATUSES: OrderStatus[] = ['preparando', 'entrega', 'finalizado'];

const Producao = () => {
  const { orders, isLoading, isError, error, refetch, changeStatus, createManualOrder } =
    useOrders();
  const [showCancelled, setShowCancelled] = useState(false);
  const [manualOrderOpen, setManualOrderOpen] = useState(false);

  const handleStatusChange = (orderId: string, newStatus: OrderStatus) => {
    changeStatus(orderId, newStatus);
    toast.success('Status atualizado', {
      description: `Pedido movido para ${ORDER_STATUS_INFO[newStatus].label}`,
    });
  };

  const columns = showCancelled ? [...KANBAN_STATUSES, 'cancelado' as OrderStatus] : KANBAN_STATUSES;
  const cancelledCount = orders.filter((order) => order.status === 'cancelado').length;

  return (
    <Page className="space-y-6">
      <PageTitle
        title="Produção"
        subtitle="Gerencie o fluxo de pedidos"
        actions={
          <>
            {/* Olho no lugar do texto: "Mostrar cancelados (0)" ocupava metade
                da faixa no celular para uma ação secundária. O contador vira um
                selo ao lado quando existe algo escondido. O `title` faz as
                vezes de dica — o projeto não usa componente de tooltip. */}
            <Button
              variant="outline"
              size="icon"
              className="relative h-11 w-11 sm:h-9 sm:w-9"
              aria-pressed={showCancelled}
              title={showCancelled ? 'Ocultar cancelados' : 'Mostrar cancelados'}
              aria-label={
                showCancelled
                  ? 'Ocultar pedidos cancelados'
                  : `Mostrar pedidos cancelados (${cancelledCount})`
              }
              onClick={() => setShowCancelled((v) => !v)}
            >
              {showCancelled ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
              {!showCancelled && cancelledCount > 0 && (
                <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-[11px] font-medium text-destructive-foreground">
                  {cancelledCount}
                </span>
              )}
            </Button>
            {/* Fallback para quando o agente de IA cai: o lojista continua
                registrando pedido (telefone, balcão) pelo mesmo cardápio,
                sem depender do WhatsApp estar respondendo. */}
            <Button
              variant="outline"
              size="icon"
              className="h-11 w-11 sm:h-9 sm:w-9"
              title="Registrar pedido manualmente"
              aria-label="Registrar pedido manualmente"
              onClick={() => setManualOrderOpen(true)}
            >
              <ClipboardPlus className="h-4 w-4" />
            </Button>
            <RefreshButton onRefresh={() => refetch()} />
          </>
        }
      />

      <CreateManualOrderDialog
        open={manualOrderOpen}
        onOpenChange={setManualOrderOpen}
        onCreate={createManualOrder}
      />

      {isError ? (
        <QueryError
          error={error}
          onRetry={() => refetch()}
          title="Não foi possível carregar os pedidos"
        />
      ) : isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {KANBAN_STATUSES.map((status) => (
            <Skeleton key={status} className="h-64 rounded-lg" />
          ))}
        </div>
      ) : (
        <div
          className={cn(
            'grid grid-cols-1 md:grid-cols-2 gap-4',
            showCancelled ? 'xl:grid-cols-4' : 'xl:grid-cols-3',
          )}
        >
          {columns.map((status) => (
            <KanbanColumn
              key={status}
              status={status}
              orders={orders.filter((order) => order.status === status)}
              onStatusChange={handleStatusChange}
            />
          ))}
        </div>
      )}
    </Page>
  );
};

export default Producao;
