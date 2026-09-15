/**
 * App principal — rotas e providers globais.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Toaster } from '@/components/ui/sonner';
import Dashboard from './pages/Dashboard';
import Conversas from './pages/Conversas';
import Producao from './pages/Producao';
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
    <>
      <Toaster />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/producao" replace />} />
          <Route path="/producao" element={<Producao />} />
          <Route path="/produtos" element={<Produtos />} />
          <Route path="/conversas" element={<Conversas />} />
          <Route path="/dashboard" element={<Dashboard />} />
          {/* Rotas antigas — mantidas para não quebrar link salvo no navegador. */}
          <Route path="/loja" element={<Navigate to="/producao" replace />} />
          <Route path="/admin" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </>
  </QueryClientProvider>
);

export default App;
