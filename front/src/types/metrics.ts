/**
 * Tipos das métricas do dashboard — substituem o antigo `mock-data.ts`.
 * Os nomes dos campos vêm em português porque espelham as views SQL.
 */

/** Períodos aceitos por `GET /api/metrics/summary?range=`. */
export type MetricsRange = 'hoje' | 'semana' | 'mes';

export interface MetricsSummary {
  total_vendas: number;
  total_pedidos: number;
  ticket_medio: number;
  variacao_percentual: number;
  por_status: Partial<Record<string, number>>;
}

/** `GET /api/metrics/daily-sales` */
export interface DailySales {
  dia: string;
  pedidos: number;
  total: number;
}

/** `GET /api/metrics/product-sales` */
export interface ProductSales {
  produto: string;
  unidades: number;
  receita: number;
}

/** `GET /api/metrics/hourly-sales` */
export interface HourlySales {
  hora: number;
  pedidos: number;
  receita: number;
}

// --- Formatos prontos para o Recharts ---------------------------------------

export interface SalesPoint {
  label: string;
  total: number;
  pedidos: number;
}

export interface ProductPoint {
  name: string;
  unidades: number;
  receita: number;
}

export interface HourlyPoint {
  label: string;
  pedidos: number;
  receita: number;
}
