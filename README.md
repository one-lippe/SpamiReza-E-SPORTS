# SpamiReza E-SPORTS

Dashboard de acompanhamento do **Clã 5 · e-SpamiReza** no campeonato interno de e-sports
(guerras avulsas — amistosos agendados e guerras do campeonato). Site no ar via GitHub Pages,
alimentado automaticamente pela API oficial do Clash of Clans (proxy RoyaleAPI).

- **`index.html`** — dashboard (o que vai pro GitHub Pages).
- **`coletor_esports.py`** — puxa `/clans/{tag}/currentwar` do clã 5, arquiva cada guerra em
  `historico/guerras.json` (upsert por guerra, nunca perde dado) e injeta o ranking acumulado
  (`DATA`) no `index.html`.
- **`.github/workflows/coletor.yml`** — roda o coletor a cada 10 min e publica no Pages.
- **`ARTES/`** — `bg.jpg` (fundo) e `FAISCAS.png` (efeito de faíscas, mesmo do dashboard de ligas).

**Configuração pendente no GitHub:** adicionar o secret `COC_TOKEN` (Settings → Secrets and
variables → Actions → New repository secret) com o token da API do Clash of Clans.

Índice (0–100): 55% ataque + 20% defesa + 25% confiabilidade — mesmo modelo do dashboard de ligas.
