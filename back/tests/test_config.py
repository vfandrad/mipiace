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


def test_a_loja_e_configuravel_sem_tocar_no_codigo(monkeypatch) -> None:
    """O que a generalização trouxe é a OPÇÃO de trocar, não um sistema sem dono.

    Os defaults continuam sendo os da Mi Piace de propósito: sem `.env`, o
    sistema é o da casa que ele atende hoje. Uma tentativa anterior deixou os
    defaults genéricos e o resultado foi um deploy em producao se apresentando
    como "Nossa Loja" — configuração esquecida virou perda de identidade.

    O que precisa ser verdade é isto: trocar as variáveis troca a loja inteira,
    sem editar uma linha de código.
    """
    padrao = Settings(_env_file=None)
    assert padrao.store_name == "Mi Piace Gelateria"

    for chave, valor in {
        "STORE_NAME": "Açaí do Bairro",
        "STORE_EMOJI": "🍧",
        "STORE_SEGMENT": "açaiteria",
        "STORE_CITY": "PORTO VELHO",
    }.items():
        monkeypatch.setenv(chave, valor)

    outra = Settings(_env_file=None)
    assert outra.store_name == "Açaí do Bairro"
    assert outra.store_emoji == "🍧"
    assert outra.store_segment == "açaiteria"
    assert outra.store_city == "PORTO VELHO"
