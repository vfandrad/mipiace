"""A configuração e o `.env.example` têm de contar a mesma história.

Antes havia quatro listas de variáveis de ambiente (`back/.env.example`,
`.env.prod.example`, os dois docker-compose e uma tabela na documentação) e
nenhuma era superconjunto da outra: os quatro `STORE_*` existiam no exemplo de
desenvolvimento e faltavam no de produção, então um deploy feito pelo DEPLOY.md
subia um bot que respondia "não sei" sobre horário e endereço.

Este teste faz do `.env.example` a lista única. Campo novo em `Settings` sem
linha no arquivo quebra aqui, que é barato, em vez de sumir num deploy.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _chaves_do_arquivo() -> set[str]:
    texto = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", texto, re.MULTILINE))


def test_env_example_cobre_toda_a_configuracao() -> None:
    faltando = {n.upper() for n in Settings.model_fields} - _chaves_do_arquivo()
    assert not faltando, (
        f"Campos em Settings sem linha no .env.example: {sorted(faltando)}. "
        "Documente-os lá — é a lista que o README manda copiar."
    )


def test_env_example_nao_inventa_variavel() -> None:
    sobrando = _chaves_do_arquivo() - {n.upper() for n in Settings.model_fields}
    assert not sobrando, (
        f"Linhas no .env.example que ninguém lê: {sorted(sobrando)}. "
        "Ou o campo saiu de Settings, ou é erro de digitação."
    )


def test_a_loja_nao_esta_escrita_no_codigo() -> None:
    """Os defaults são genéricos: o nome do cliente mora no ambiente.

    É o que permite subir a mesma imagem para uma segunda empresa mudando só o
    `.env` — e o que impede o nome de uma loja vazar na cobrança de outra.
    """
    padrao = Settings(_env_file=None)
    assert "piace" not in padrao.store_name.lower()
    assert "piace" not in padrao.app_name.lower()
    assert padrao.store_segment == "loja"
