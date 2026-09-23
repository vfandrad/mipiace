/**
 * Tipos do catálogo (produtos > grupos > complementos).
 *
 * Espelham `back/db/schema.sql`. O `GET /api/products` devolve a árvore já
 * aninhada, então o front não precisa mais cruzar três listas na mão.
 */

/**
 * Classificação de complemento que vale em qualquer produto ("Sem lactose",
 * "Vegetariano"). É atributo do complemento, não do grupo de escolha, e quem
 * define a lista é o lojista — numa gelateria não são as mesmas de uma
 * hamburgueria.
 */
export interface ComplementCategory {
  id: string;
  name: string;
  sort_order?: number;
}

export interface Complement {
  id: string;
  group_id: string;
  name: string;
  extra_price: number;
  is_available: boolean;
  sort_order?: number;
  /** null = complemento sem classificação. */
  category_id?: string | null;
}

export interface ComplementGroup {
  id: string;
  product_id: string;
  name: string;
  min_choices: number;
  max_choices: number;
  is_required: boolean;
  sort_order?: number;
  complements: Complement[];
}

export interface Product {
  id: string;
  name: string;
  description?: string | null;
  base_price: number;
  is_available: boolean;
  sort_order?: number;
  groups: ComplementGroup[];
}

/** Resposta de `GET /api/products`. */
export interface ProductListResponse {
  products: Product[];
}

// --- Payloads de escrita -----------------------------------------------------

export interface ProductInput {
  name: string;
  description?: string | null;
  base_price: number;
  is_available: boolean;
}

export interface GroupInput {
  name: string;
  min_choices: number;
  max_choices: number;
  is_required: boolean;
}

export interface ComplementCategoryInput {
  name: string;
  sort_order?: number;
}

export interface ComplementInput {
  name: string;
  extra_price: number;
  is_available: boolean;
  category_id?: string | null;
}

/** O que pode ser reordenado arrastando no painel. */
export type ReorderKind = 'product' | 'group' | 'complement' | 'category';

/** Tipo de entidade do catálogo — usado nas rotas genéricas de PATCH/DELETE. */
export type CatalogEntity = 'product' | 'group' | 'complement' | 'category';
