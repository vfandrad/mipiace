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

/**
 * Um grupo COMO ESTE PRODUTO O USA.
 *
 * A lista de complementos ("Sabores") é compartilhada: os três tamanhos de pote
 * usam a mesma, e por isso marcar um sabor como esgotado vale para todos. O que
 * muda por produto é quantas escolhas ele pede — e é isso que mora no vínculo.
 *
 * `id` é do vínculo (é o que se edita ou se remove para tirar o grupo DESTE
 * produto); `group_id` é da lista compartilhada.
 */
export interface ComplementGroup {
  id: string;
  group_id: string;
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

/**
 * Payload de "usar um grupo neste produto".
 *
 * Ou aponta uma lista existente (`group_id`) — o "importar grupo" — ou cria uma
 * nova pelo nome. Nunca os dois: o backend recusa.
 */
export interface GroupInput {
  group_id?: string;
  name?: string;
  min_choices: number;
  max_choices: number;
  is_required: boolean;
}

/** Uma lista da biblioteca, como `GET /api/groups` devolve. */
export interface GroupLibraryEntry {
  id: string;
  name: string;
  sort_order?: number;
  complements: Complement[];
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
export type ReorderKind = 'product' | 'product_group' | 'complement' | 'category';

/** Tipo de entidade do catálogo — usado nas rotas genéricas de PATCH/DELETE. */
export type CatalogEntity = 'product' | 'group' | 'complement' | 'category';
