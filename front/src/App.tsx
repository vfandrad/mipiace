/**
 * App principal — rotas e providers globais.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Toaster } from '@/ui';
import Dashboard from '@/pagina-dashboard';
import Conversas from '@/pagina-conversas';
import Producao from '@/pagina-producao';
import Produtos from '@/pagina-produtos';

/** Rota que não existe. Quinze linhas não merecem arquivo próprio. */
const NotFound = () => (
  <div className="flex min-h-screen-safe items-center justify-center bg-muted">
    <div className="text-center">
      <h1 className="mb-4 text-4xl font-bold">404</h1>
      <p className="mb-4 text-xl text-muted-foreground">Página não encontrada</p>
      <a href="/" className="text-primary underline hover:text-primary/90">Voltar ao início</a>
    </div>
  </div>
);

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
