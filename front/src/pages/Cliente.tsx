/**
 * Página do cliente — simula WhatsApp Web para fazer pedidos.
 */

import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Send } from 'lucide-react';
import { sendClientMessage, fetchConversations } from '@/lib/api';
import { toast } from 'sonner';

interface Message {
  id: string;
  content: string;
  sender: 'user' | 'bot';
  timestamp: Date;
}

export default function Cliente() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  // Busca conversas do usuário
  useQuery({
    queryKey: ['client-conversations', phoneNumber],
    queryFn: async () => {
      if (!phoneNumber) return [];
      const allConversations = await fetchConversations();
      return allConversations.filter(
        (c: any) => c.phone_number === phoneNumber || c.phone === phoneNumber,
      );
    },
    enabled: !!phoneNumber,
  });

  // Auto-scroll para última mensagem
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !phoneNumber) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      content: input,
      sender: 'user',
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      // Envia mensagem (real ou simulador, conforme configuração)
      await sendClientMessage({
        phone_number: phoneNumber,
        message: input,
      });

      // Simula resposta do bot (em produção real viria via webhook)
      const botMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: '✓ Mensagem recebida. Agente processando...',
        sender: 'bot',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, botMessage]);

      if (!conversationId) {
        setConversationId(Date.now().toString());
      }

      queryClient.invalidateQueries({ queryKey: ['client-conversations', phoneNumber] });
    } catch (error) {
      toast.error('Erro ao enviar mensagem');
      console.error(error);

      // Remove mensagem do usuário em caso de erro
      setMessages((prev) => prev.filter((msg) => msg.id !== userMessage.id));
    } finally {
      setLoading(false);
    }
  };

  const handleStartConversation = (phone: string) => {
    setPhoneNumber(phone);
    setMessages([]);
    setConversationId(null);

    const greeting: Message = {
      id: Date.now().toString(),
      content: '👋 Olá! Bem-vindo à Mi Piace Gelateria. Como posso ajudá-lo?',
      sender: 'bot',
      timestamp: new Date(),
    };
    setMessages([greeting]);
  };

  if (!phoneNumber) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-green-50 to-blue-50">
        <div className="w-full max-w-md p-8 bg-white rounded-lg shadow-lg">
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-bold text-gray-800">Mi Piace</h1>
            <p className="text-gray-600 mt-2">Faça seu pedido via WhatsApp</p>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              const phone = (e.target as HTMLFormElement).phone.value.trim();
              if (phone) handleStartConversation(phone);
            }}
            className="space-y-4"
          >
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Seu número de WhatsApp
              </label>
              <Input
                type="tel"
                name="phone"
                placeholder="55 11 98765-4321"
                required
                className="w-full"
              />
            </div>
            <Button type="submit" className="w-full bg-green-600 hover:bg-green-700">
              Conectar
            </Button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      {/* Header */}
      <div className="flex items-center justify-between p-4 bg-green-600 text-white shadow-md">
        <div>
          <h1 className="font-bold">Mi Piace Gelateria</h1>
          <p className="text-sm text-green-100">{phoneNumber}</p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setPhoneNumber('');
            setMessages([]);
            setConversationId(null);
          }}
          className="text-white hover:bg-green-700"
        >
          Sair
        </Button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'} mb-3`}
          >
            <div
              className={`max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                msg.sender === 'user'
                  ? 'bg-green-600 text-white rounded-br-none'
                  : 'bg-gray-200 text-gray-800 rounded-bl-none'
              }`}
            >
              <p className="text-sm break-words">{msg.content}</p>
              <p className="text-xs mt-1 opacity-70">
                {msg.timestamp.toLocaleTimeString('pt-BR', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </p>
            </div>
          </div>
        ))}
        <div ref={scrollRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSendMessage} className="p-4 border-t flex gap-2 bg-white">
        <Input
          type="text"
          placeholder="Digite sua mensagem..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
          className="flex-1"
        />
        <Button
          type="submit"
          disabled={loading || !input.trim()}
          size="icon"
          className="bg-green-600 hover:bg-green-700"
        >
          <Send className="w-4 h-4" />
        </Button>
      </form>
    </div>
  );
}
