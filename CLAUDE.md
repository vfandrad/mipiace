# Instruções para o Claude Code neste repositório

## Protocolo: depois de corrigir um bug ou problema de infra

O usuário autorizou, de forma permanente, que qualquer correção verificada
(testes passando, `ruff`/lint limpo) siga direto para produção sem pedir
confirmação a cada etapa. Ao terminar uma correção:

1. **Commit** — arquivos específicos por nome (nunca `git add -A`/`.`),
   mensagem em português explicando o *porquê* da mudança, terminando com a
   linha de atribuição do Claude Code em uso na sessão.
2. **Push** para `origin main`.
3. **Redeploy na VPS de produção.** O Easypanel deste projeto não redeploya
   sozinho a partir do GitHub (sem webhook configurado), então é manual:
   ```bash
   ssh root@<IP da VPS>          # peça IP/senha ao usuário se não estiverem na conversa
   cd /etc/easypanel/projects/mi-piace/mi-piace/code
   git pull origin main
   docker compose -p mi-piace_mi-piace \
     -f docker-compose.easypanel.yml -f docker-compose.override.yml \
     --env-file .env up -d --build --no-deps <serviço(s) afetado(s)>
   ```
   - Use `--build` só quando `back/Dockerfile`, `back/requirements.lock.txt`
     ou código do backend mudou. Mudança só em `docker-compose.easypanel.yml`
     (ex.: limites de recursos) não precisa `--build`.
   - Pode listar vários serviços na mesma chamada (`... backend frontend`).
   - Containers: `mi-piace_mi-piace-{backend,frontend,db,evolution-api,
     evolution-db,evolution-redis}-1`.
4. **Verificar no ar** antes de considerar terminado:
   ```bash
   curl https://api.mipiace.vfandrade.com/health   # espera "database":"ok"
   docker ps --format '{{.Names}}\t{{.Status}}'    # espera "healthy" nos containers com healthcheck
   ```

## O que fica de fora deste protocolo — nunca fazer sozinho

Ações que mudam configuração de sistema/segurança do servidor (`ufw`
enable/disable, por exemplo) o Claude Code bloqueia por padrão, e continuam
sendo do usuário mesmo com essa autorização de deploy. Nesses casos: prepare
o comando exato, explique o que ele faz e por quê, e peça para o usuário
rodar — nunca tente contornar o bloqueio.

## Contexto do projeto

- [PROJECT.md](PROJECT.md) — como o sistema funciona, arquivo por arquivo.
- [DEPLOY.md](DEPLOY.md) — subir do zero, backup do banco, controle de
  migração (`back/db/apply_migrations.sh`).

## Princípios que não podem ser quebrados numa correção

- A LLM nunca inventa produto, preço, taxa ou disponibilidade — ela traduz a
  mensagem em operação estruturada; o backend calcula dinheiro e valida.
  Ver as seções de fechamento e de operações em `back/app/agente.py`.
- Nenhuma taxa (entrega, etc.) é assumida por padrão quando o cliente não
  decidiu ainda — mostrar um total como se a escolha já tivesse sido feita é
  o mesmo tipo de erro que inventar um valor.
- Correção de bug não é licença para aumentar complexidade: preferir o menor
  ajuste que resolve o problema relatado.
