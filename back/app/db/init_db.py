"""Aplica `db/schema.sql` (e opcionalmente `db/seed.sql`) num banco vazio.

No Docker isso é feito pelo entrypoint do Postgres. Este módulo existe para o
caminho "sem Docker": `python -m app.db.init_db [--seed] [--force]`.

Não é uma ferramenta de migração — é só o atalho de bootstrap local.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy import text

from app.db.session import dispose_engine, get_engine

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parents[2] / "db"
SCHEMA_FILE = DB_DIR / "schema.sql"
SEED_FILE = DB_DIR / "seed.sql"


async def schema_exists() -> bool:
    """Usa a tabela `products` como sentinela do schema já aplicado."""
    engine = get_engine()
    async with engine.connect() as conn:
        found = await conn.scalar(text("SELECT to_regclass('public.products')"))
    return found is not None


async def run_sql_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"arquivo SQL não encontrado: {path}")
    sql = path.read_text(encoding="utf-8")
    engine = get_engine()
    async with engine.begin() as conn:
        # exec_driver_sql: psycopg aceita várias instruções num único envio,
        # o que preserva os blocos $fn$ ... $fn$ do schema.sql.
        await conn.exec_driver_sql(sql)
    logger.info("SQL aplicado: %s", path.name)


async def init_db(*, seed: bool = False, force: bool = False) -> None:
    if await schema_exists() and not force:
        logger.info("Schema já existe; nada a fazer (use --force para reaplicar).")
        return
    await run_sql_file(SCHEMA_FILE)
    if seed:
        await run_sql_file(SEED_FILE)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Cria o schema do Mi Piace.")
    parser.add_argument("--seed", action="store_true", help="também aplica o seed")
    parser.add_argument(
        "--force", action="store_true", help="reaplica mesmo se já existir"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        await init_db(seed=args.seed, force=args.force)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
