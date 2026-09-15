/**
 * App principal — rotas e providers globais.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import Admin from './pages/Admin';
import Cliente from './pages/Cliente';
import Conversas from './pages/Conversas';
import Loja from './pages/Loja';
import NotFound from './pages/NotFound';
import Produtos from './pages/Produtos';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Erro de chave/rota não melhora repetindo: uma tentativa extra basta.
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/loja" replace />} />
          <Route path="/loja" element={<Loja />} />
          <Route path="/produtos" element={<Produtos />} />
          <Route path="/conversas" element={<Conversas />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/cliente" element={<Cliente />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
