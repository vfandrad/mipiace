/**
 * O som de "chegou pedido novo" no Kanban.
 *
 * Gerado na hora pelo Web Audio API, em vez de um arquivo de áudio: evita
 * carregar um asset extra e funciona em qualquer navegador sem depender de
 * onde o arquivo foi hospedado. O `AudioContext` é criado uma vez só e
 * reaproveitado — criar um por toque é mais pesado e alguns navegadores
 * limitam quantos existem ao mesmo tempo.
 */

let contexto: AudioContext | null = null;

function getContexto(): AudioContext | null {
  if (contexto) return contexto;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  contexto = new Ctor();
  return contexto;
}

function tocarTom(ctx: AudioContext, frequencia: number, inicioEm: number, duracao: number): void {
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.value = frequencia;
  // Sobe rápido e desce suave: evita o "clique" de ligar/desligar o tom seco.
  gain.gain.setValueAtTime(0, inicioEm);
  gain.gain.linearRampToValueAtTime(0.3, inicioEm + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, inicioEm + duracao);
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  oscillator.start(inicioEm);
  oscillator.stop(inicioEm + duracao);
}

/** Dois tons curtos (dó-mi), como uma campainha de balcão. */
export function tocarNotificacaoDePedidoNovo(): void {
  try {
    const ctx = getContexto();
    if (!ctx) return;
    if (ctx.state === 'suspended') void ctx.resume();
    const agora = ctx.currentTime;
    tocarTom(ctx, 523.25, agora, 0.18); // dó
    tocarTom(ctx, 659.25, agora + 0.14, 0.22); // mi
  } catch {
    // Navegador sem áudio, ou bloqueou por falta de interação ainda — a tela
    // continua funcionando normalmente, só sem o som desta vez.
  }
}
