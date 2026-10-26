# Instruções — Migração CMM (Cinema e Muito +) para site estático

> **Arquivo de retomada.** Ler este documento antes de qualquer ação.
> Última atualização: 2026-10-24
> Status geral: **Fases 0–7 aprovadas; identidade visual concluída; GSC/Cloudflare em andamento**.
> Próxima etapa: **concluir GSC e cache da Cloudflare; depois v2.0 (e-mail)**.

---

## REGRA DE TRABALHO (OBRIGATÓRIA)

1. Executar **uma fase por vez**.
2. Ao terminar uma fase, apresentar:
   - o que foi feito;
   - arquivos gerados/alterados;
   - resultados dos testes/medições;
   - pendências e riscos.
3. **Parar e aguardar aprovação explícita do usuário.**
4. Não iniciar a fase seguinte sem a palavra “aprovado” (ou equivalente).
5. Atualizar este arquivo ao fim de cada fase: marcar status, data e observações.
6. Não cancelar a hospedagem antiga em nenhuma fase antes da Fase 7 concluída e validada.

Modelo de status por fase:

```text
Status: [ ] não iniciada  [ ] em andamento  [x] concluída  [ ] aprovada
Data:
Resultado:
Aprovação do usuário:
```

---

## 1. Contexto do projeto

- Site atual: `https://www.cinemaemuitomais.com`
- Blog de cinema, teatro, TV, literatura e cultura pop, com conteúdo desde ~2010.
- O servidor atual será desligado por falta de orçamento.
- Objetivo: converter em site estático, preservar URLs, SEO, acessos e o domínio.
- Destino: **GitHub Pages** (HTML) + **Cloudflare** (DNS/proxy/regras) + **Cloudflare R2** (imagens).
- O site atual ainda está no ar. **Não desligar a hospedagem até o novo site estar validado.**

### Ambiente local

- Projeto raiz: `C:\Users\dayan\Downloads\migracao-sites`
- Site WordPress/backup: `C:\Users\dayan\Downloads\migracao-sites\CMM`
- Pasta deste projeto: `C:\Users\dayan\Downloads\migracao-sites\site-estatico-cmm`
- Playbook de referência: `C:\Users\dayan\Downloads\migracao-sites\site-estatico\MIGRAR-WP-PARA-ESTATICO.md`

Ferramentas disponíveis:
- Node.js e npm
- Python 3.14
- Git
- curl
- Docker instalado, mas **daemon parado**
- PHP, MySQL/MariaDB e WP-CLI **não instalados**

Observação operacional:
- O site ao vivo responde 406 para User-Agent simples.
- Funciona com User-Agent completo de navegador + headers `Accept`, `Accept-Language`, `Sec-Fetch-*`.
- Exemplo de UA que funcionou:
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36`

---

## 2. Decisões aprovadas pelo usuário

| Tema | Decisão |
|---|---|
| HTML | GitHub Pages |
| Imagens/uploads | Cloudflare R2 em `media.cinemaemuitomais.com` |
| Layout | Tema leve inspirado no Zeen, preservando identidade visual |
| Anúncios | Manter AdSense |
| Analytics | Manter GA4 |
| Consentimento | Manter banner de consentimento + Consent Mode v2 |
| Tags | Gerar **todas** as tags em versão mínima (page 1) |
| Paginação de tags | Gerar paginação das 349 bases com tráfego |
| Comentários | Manter os existentes como HTML estático, sem novos comentários |
| Publicação futura | Site congela na data da migração; novos posts exigirão novo fluxo |

---

## 3. Inventário técnico levantado

### WordPress
- WordPress 7.0.7
- Tema: **Zeen 3.6.7** + `zeen-child`
- Permalink: `/%postname%/`
- Home estática: página ID 39
- Idioma: `pt_BR`
- Timezone: `America/Sao_Paulo`
- Plugin SEO: Yoast SEO 28.3
- Plugins ativos:
  - Akismet
  - Complianz GDPR
  - Google Site Kit
  - GotMLS
  - Jetpack
  - Let's Info Up
  - Let's Live Blog
  - Let's Social Count
  - SSL Insecure Content Fixer
  - UpdraftPlus
  - Wordpress SEO (Yoast)
  - Zeen Engine
- Também presentes no backup: Better WP Security, OneSignal, WP Rocket (WP_CACHE false), WP2Static não usado.

### Conteúdo publicado
- **4.596 posts**
- **191 páginas**
  - 178 são páginas de cinema em `/programacao/cinema/...`
  - demais: home, quem somos, contato, colunas, políticas, link, mapa do site etc.
- **14.847 tags** no sitemap
- **8 categorias**
- **5 autores**
- 4.647 anexos
- 305 comentários no campo `comment_count` (319 registros na tabela)

### Banco de dados
- Banco atual: `gabriel_cinemaemuitoma`
- Prefixo: `wp4LG7q9Gf_`
- Dump atual: `CMM\gabriel_cinemaemuitoma.sql.gz` (16,4 MB)
- Dump antigo 2010–2014: `CMM\gabriel_cinemaemuitoma01.sql.gz` (4,1 MB)
  - 1.117 posts e 137 páginas publicados
  - útil para mapear URLs antigas que sumiram e precisam de redirect

### Backup de arquivos
- `CMM\backup-cinemaemuitomais.com-10-20-2026.tar.gz` (9,28 GB)
- Contém o home cPanel inteiro, incluindo `public_html`, `tmp`, logs etc.
- **Não extrair tudo sem necessidade.**
- `public_html/wp-content/uploads`: **6,73 GB / 59.936 arquivos**
- Referenciados no conteúdo + featured images:
  - ~2.870 arquivos encontrados
  - ~1,29 GB
  - **2.160 referências sem arquivo correspondente** no backup (auditar)
- Tipos: PNG 3,53 GB; JPG 2,88 GB; JPEG 160 MB; WebP 129 MB.

### HTML atual
- 160–220 KB por página
- Removendo scripts/styles/comentários: 96–124 KB
- Páginas usam Jetpack CDN (`i0.wp.com`) para imagens
- Fontes: **Fira Sans** e **Work Sans** (Google Fonts)
- AdSense: `ca-pub-6725457701341059`
- Sem formulário de contato real (apenas formulário de busca)

### SEO
- Yoast `indexable` contém permalinks e metadados:
  - terms: 16.665
  - posts/anexos: 9.467
  - home-page: 31
  - users: 9
  - system-page: 5
- Usar `yoast_indexable.permalink` como fonte de verdade das URLs.
- Sitemap atual:
  - posts: 5 arquivos / 4.596 URLs
  - páginas: 191
  - anexos: 4 arquivos (excluir da versão estática)
  - categorias: 8
  - tags: 15 arquivos / 14.847
  - autores: 5

---

## 4. Dados GA4/GSC — leitura importante

### Relatórios disponíveis em `CMM\`
- `Resumo_dos_relatórios.csv` (28 dias: 2026-09-22 a 2026-10-19)
- `Visão_geral_da_aquisição.csv` (2026-01-01 a 2026-10-20)
- `Visão_geral_da_monetização.csv`
- `Visão_geral_do_engajamento.csv`
- Codificação: UTF-8

### Totais GA4 2026
- **291.415 pageviews**
- 21.481 títulos de página
- 16.532 títulos são arquivos (`Archives`)
- 15.076 bases de arquivo
- 1.805 linhas de arquivo paginado
- 349 bases com paginação

### Qualidade do tráfego (crítico)
- ~97% dos usuários vêm de **Direct/Singapore**:
  - 72.925 de 75.067 usuários por cidade
  - 277.465 de 282.208 primeiros usuários por canal
- Isso indica **tráfego de bot/spam**, não audiência real.
- **Não usar GA4 sozinho para priorizar.**
- Sinal confiável: **Google Search Console** presente no relatório de aquisição:
  - 1.378.004 impressões orgânicas
  - 1.362 landing pages
  - 171 páginas de cinema concentram 1.297.353 impressões
  - 1.033 posts/páginas com impressões
  - 104 tags com impressões

### Relação GA4 × conteúdo
- 4.755 títulos de conteúdo casados com posts/páginas.
- 157 títulos não casados:
  - home
  - 404
  - nomes antigos de cinemas
  - páginas de anexos (WhatsApp Image etc.)
  - variações de título
- Todos os 4.787 posts/páginas publicados serão preservados independentemente do match.

### Monetização
- Receita total registrada em 2026: **10,819** (AdSense; compras = 0)
- Receita muito baixa. Ainda assim, o usuário optou por manter AdSense.

---

## 5. Restrições de plataforma (confirmadas)

| Plataforma | Limite |
|---|---|
| GitHub Pages | site publicado ≤ **1 GB**; builds ≤ 10 min; banda soft 100 GB/mês |
| Cloudflare Pages Free | **20.000 arquivos**; 25 MiB por arquivo |
| Cloudflare R2 Free | **10 GB** de armazenamento; egress grátis; 1M Class A / 10M Class B por mês |

Consequências:
- Imagens **não podem** ficar no GitHub Pages.
- HTML precisa ser leve: alvo ~330 MB no total.
- Orçamento:
  - posts/páginas: ~190 MB
  - tags/arquivos: ~140 MB
  - índice de busca: ~15 MB
  - assets: ~5 MB
- Mídia no R2: alvo < 3 GB após WebP.

---

## 6. Entregáveis privados da análise (Fase 1)

Criar em `site-estatico-cmm\dados\analise-2026\` (fora do git):

### `paginas-posts-2026.csv`
Uma linha por post/página (4.787), colunas:

```text
prioridade,url,titulo,tipo,status,publicado_em,views_ga_2026,usuarios_ga_28d,impressoes_gsc,paginas_total,acao
```

Prioridades:
- **P0**: home + 191 páginas + conteúdo com impressão no GSC + top 100 GA.
- **P1**: demais posts/páginas publicados.
- **P2**: tags/categorias/autores com sinal GSC/GA.
- **P3**: demais tags (geradas em versão mínima).

### `arquivos-2026.csv`
```text
prioridade,url,tipo,base,views_ga_2026,impressoes_gsc,paginas_total,paginas_gerar
```

### `midia-referenciada.csv`
```text
url_original,arquivo_local,tamanho_bytes,usado_em,status
```

### `resumo-analise.md`
- metodologia;
- totais;
- aviso sobre tráfego de bot;
- decisões de priorização.

### `urls-para-verificacao.txt`
- todas as URLs que devem responder 200 na versão estática.

Regras de mapeamento:
1. URL canônica vem de `yoast_indexable.permalink`.
2. GA4 casa por título normalizado (entidades HTML, aspas curvas, espaços, sufixo do site).
3. GSC casa por URL e resolve casos ambíguos de títulos antigos.
4. Conferência manual dos 157 títulos não casados.
5. Nunca usar o tráfego direto de Singapura como critério de prioridade.

---

## 7. Estrutura de pastas planejada

```text
site-estatico-cmm/
  INSTRUCOES-MIGRACAO.md
  dados/                     # privado, gitignored (dumps, análises, listas)
    brutos/
    analise-2026/
  src/
    templates/
      base.html
      post.html
      page.html
      archive.html
      home.html
      search.html
      404.html
    assets/
      css/
      js/
      fonts/
      img/
    data/                    # JSON sanitizado, pode ser commitado
    scripts/
      export-db.py
      build.py
      media.py
      sitemaps.py
  site/                      # saída gerada, gitignored
  .github/workflows/deploy.yml
  CNAME
  .nojekyll
  README.md
```

Segurança:
- `.gitignore` deve excluir:
  - `*.sql.gz`
  - `*.tar.gz`
  - `dados/brutos/`
  - `dados/analise-2026/`
  - `site/`
  - `wp-config.php`
  - `DEPLOY-LOCAL.md`
- Nunca commitar senhas, hashes, e-mails de usuários, chaves do Jetpack/OneSignal/Google.
- Rotacionar chaves expostas após a migração.

---

## 8. Fases de execução

> Repetir para cada fase: executar → testar → apresentar resultado → aguardar aprovação.

---

### Fase 0 — Segurança, baseline e preparação

**Objetivo:** garantir que nada será perdido e registrar o estado atual.

Tarefas:
- [x] Confirmar que a hospedagem antiga continua ativa.
- [x] Confirmar integridade dos backups:
  - `gabriel_cinemaemuitoma.sql.gz`
  - `backup-cinemaemuitomais.com-10-20-2026.tar.gz`
- [x] Criar `.gitignore` do projeto.
- [x] Registrar baseline Lighthouse (mobile + desktop):
  - home
  - um post comum
  - uma página de cinema
  - uma tag
  - 404
- [x] Registrar baseline de GSC/GA4.
- [x] Documentar credenciais/IDs públicos (AdSense, GA4) sem expor segredos.

Entregáveis:
- `dados/baseline/fase-0-relatorio.md`
- `dados/baseline/ga4-gsc-baseline.md`
- `dados/baseline/lighthouse/*.json`
- `.gitignore`
- confirmação de backup

Critério de aprovação:
- Backups íntegros.
- Baseline registrado.
- Nenhuma alteração no site atual.

Status: **[x] concluída — aprovada pelo usuário**
Data: 2026-10-20
Resultado: backup validado (SQL CRC OK; tar com 86.508 entradas); baseline Lighthouse de 5 páginas em mobile/desktop registrado; GA4/GSC documentados; nenhuma alteração em produção.
Aprovação do usuário: **aprovada**

---

### Fase 1 — Análise GA4/GSC e lista de URLs

**Objetivo:** produzir a lista de páginas/posts que não podem desaparecer.

Tarefas:
- [x] Exportar do dump SQL: posts, páginas, termos, relações, mídia, autores, Yoast.
- [x] Normalizar e casar títulos GA4 com posts/páginas.
- [x] Cruzar com GSC (impressões por URL).
- [x] Classificar P0/P1/P2/P3.
- [x] Auditar as 2.160 mídias referenciadas e não encontradas.
- [x] Gerar os arquivos da seção 6.
- [x] Apresentar resumo com totais e top 50 P0.

Entregáveis:
- `dados/analise-2026/paginas-posts-2026.csv`
- `dados/analise-2026/arquivos-2026.csv`
- `dados/analise-2026/midia-referenciada.csv`
- `dados/analise-2026/resumo-analise.md`
- `dados/analise-2026/urls-para-verificacao.txt`

Critério de aprovação:
- Todos os 4.787 posts/páginas presentes.
- Lista P0 coerente com GSC.
- Casos não casados documentados.
- Nenhum segredo nos arquivos gerados.

Status: **[x] concluída — aprovada pelo usuário**
Aprovação do usuário: **aprovada**

Notas da execução:
- Script: `src/scripts/analise-fase1.py` (parser SQL sem MySQL + parser GA4/GSC).
- Totais: 4.787 posts/páginas (4.596 posts + 191 páginas; 179 em `/programacao/`), 16.622 tags, 10 categorias, 6 autores, 349 bases de arquivo identificadas.
- GSC casado: 1.374.638 impressões em conteúdo (1.297.353 nas páginas de cinema, batendo com a referência) + 1.362 em arquivos.
- Prioridades: P0=1.212, P1=3.575; arquivos P2=13.597, P3=3.191.
- Mídia: 5.027 referenciadas (2.828 exatas, 39 originais por sufixo de tamanho, 2.160 faltantes), ~1,29 GB referenciados.
- 150 bases de GA não casadas (títulos antigos/truncados) listadas em `arquivos-2026.csv` como `arquivo-desconhecido` para revisão manual.
- Nenhum segredo incluído nos entregáveis.

---

### Fase 2 — Extração e mapa de URLs

**Objetivo:** transformar o dump em dados limpos e definir todas as rotas.

Tarefas:
- [x] Criar exportador Python sem dependência de MySQL.
- [x] Gerar JSON sanitizado em `src/data/`.
- [x] Gerar URLs canônicas de posts, páginas, tags, categorias e autores.
- [x] Gerar paginação (`/page/N/`).
- [x] Gerar mapa de redirects:
  - anexos → post pai;
  - URLs antigas do dump 2010–2014;
  - `/tarantino-fala-sobre-star-trek/colunacliche`;
  - `?p=ID`, `?page_id=ID`, `?s=`;
  - `/wp-admin/*`, `/wp-login.php`, `/xmlrpc.php`, `/feed/*` → 410.
- [x] Validar contagem de URLs contra Yoast/sitemaps.

Entregáveis:
- `src/data/*.json`
- `src/data/url-map.json`
- `src/data/redirects.json`
- relatório de contagem

Critério de aprovação:
- 4.596 posts + 191 páginas + 14.847 tags mapeados.
- Nenhuma URL duplicada.
- Redirects documentados.

Status: **[x] concluída — aprovada pelo usuário**

Notas da execução:
- Scripts: `src/scripts/wpdb.py` (parser SQL/PHP), `src/scripts/export-db.py`, `src/scripts/validar-sitemaps.py`.
- JSON gerados: `site.json`, `posts.json`, `pages.json`, `tags.json`, `categories.json`, `authors.json`, `media.json`, `url-map.json`, `redirects.json`.
- Contagem validada contra os sitemaps do Yoast (baixados em `dados/brutos/sitemaps/`):
  - posts: 4.596 no sitemap = 4.596 no url-map (0 faltando, 0 sobrando);
  - páginas: 191 no sitemap; url-map tem 190 + a home (`/`, tipo `home`) = 191;
  - tags: 14.847 no sitemap, todas presentes no url-map; geramos 16.622 tags (1.775 P3 fora do sitemap, marcadas `in_sitemap=false`);
  - categorias: 8 no sitemap, 10 no url-map (2 vazias marcadas `in_sitemap=false`);
  - autores: 5 = 5.
- `url-map.json`: 21.995 entradas (4.596 posts, 190 páginas, 1 home, 1 busca, 16.622 tags, 10 categorias, 5 autores, 570 páginas de paginação). Zero URLs duplicadas.
- `redirects.json`: 7.141 regras (3.378 × 301, 3.763 × 410) + regras de query (`?p`, `?page_id`, `?attachment_id`, `?s`, `?rest_route`, `?preview`). Motivos: anexos 4.597; conteúdo antigo removido 2.487; termos antigos 43; WordPress 10; feeds 2; slug antigo 1; URL malformada 1.
- Política aplicada: conteúdo antigo que ainda existe → 301 para a URL atual; conteúdo removido → 410; endpoints WordPress/feeds → 410.
- Mídia: 4.647 anexos exportados; 4.468 com dimensões; 3.421 mapeados para post pai (`attachment_id_map`).
- Comentários: 305 aprovados preservados.
- Nenhum segredo (e-mail, senha, IP) incluído nos JSON.

---

### Fase 3 — Gerador estático e tema leve

**Objetivo:** criar o gerador e o layout inspirado no Zeen.

Tarefas:
- [x] Criar templates base/post/page/archive/home/search/404.
- [x] Criar CSS com variáveis de cor e tipografia.
- [x] Self-host de Fira Sans e Work Sans (woff2).
- [x] JS vanilla: menu, busca, consentimento, fachada de YouTube.
- [x] Renderizar blocos Gutenberg como HTML.
- [x] Converter shortcodes:
  - `[gallery]` (12)
  - `[caption]` (11)
  - `[infobox]` (6)
  - `[box]` (4)
  - `[youtube]` (4)
  - `[embed]` (1)
  - `[bfabinder]` (28)
- [x] Remover scripts de anúncio inline, Jetpack e `i0.wp.com`.
- [x] Reescrever links internos para relativos; manter canonical/og absolutos.
- [x] Implementar AdSense + consentimento:
  - sem anúncios em tags, busca e 404;
  - anúncios em posts/páginas somente após consentimento;
  - Consent Mode v2.
- [x] Implementar busca Pagefind.

Entregáveis:
- `src/templates/*`
- `src/assets/*`
- `src/scripts/build.py` funcional em amostra
- página de teste local

Critério de aprovação:
- Home, post, página de cinema, tag e 404 renderizam corretamente.
- Mobile funcional.
- Sem scripts de terceiros antes do consentimento.

Status: **[x] concluída — aprovada pelo usuário**
Aprovação do usuário: **aprovada em 2026-10-21**

Notas da execução:
- Scripts: `src/scripts/build.py` (gerador Jinja2) e `src/scripts/content.py` (Gutenberg, shortcodes, mídia e links 301/410).
- Templates: `base`, `home`, `post`, `page`, `archive`, `search`, `404`, `teste` e partials (`header`, `footer`, `consent`, `card`, `pagination`, `share`).
- Assets: `main.css`, `main.js`, fontes Fira Sans/Work Sans self-hosted e favicon SVG. Dependência Python registrada em `requirements.txt` (`Jinja2==3.1.6`).
- Build de amostra:
  - comando: `python src/scripts/build.py --sample --pagefind --media-base "https://www.cinemaemuitomais.com/wp-content/uploads"`;
  - 635 arquivos, 371 HTML, 6,3 MB, ~16 s;
  - Pagefind indexou 235 páginas / 5.650 palavras (`pt-br`);
  - 0 links locais quebrados.
- Validação visual (Puppeteer/Chrome headless):
  - home, post, tag, página de cinema e 404 em 1440 px e 390 px;
  - sem overflow horizontal em 390 px;
  - cabeçalho usa menu compacto até 1279 px e menu completo a partir de 1280 px.
- Privacidade/consentimento:
  - 0 scripts/iframes de terceiros e 0 requisições de terceiros antes do aceite;
  - anúncios e GA4 carregados somente após “Aceitar”;
  - “Recusar” mantém 0 requisições de terceiros e persiste a escolha;
  - link “Preferências de cookies” reabre o banner.
- Busca: Pagefind funcional em `/busca/?q=...`, com campo único e consulta preenchida; YouTube só carrega iframe `youtube-nocookie.com` após clique.
- Imagens faltantes (2.160 da Fase 1) ficam ocultas com placeholder visual; tratamento definitivo foi iniciado na Fase 4.
- O modo `--all` foi executado na Fase 5; a amostra acima permanece como referência de regressão.

---

### Fase 4 — Mídia e Cloudflare R2

**Objetivo:** servir imagens otimizadas fora do GitHub Pages.

Tarefas:
- [x] Extrair somente mídia usada.
- [x] Auditar os 2.160 arquivos faltantes por basename/URL decode; gerar placeholders para os sem original.
- [x] Gerar WebP em 400/800/1200/1600 px + fallback.
- [x] Manter PDFs e arquivos não-imagem necessários.
- [x] Subir para R2 preservando `/wp-content/uploads/ano/mes/...`.
- [x] Configurar domínio `media.cinemaemuitomais.com`.
- [x] Configurar cache imutável.
- [x] Gerar `media-manifest.json`.
- [x] Auditar peso local (1,80 GB; alvo < 3 GB).
- [x] Desativar Hotlink Protection para o host `media.cinemaemuitomais.com` (Configuration Rule).

Entregáveis:
- bucket R2 populado
- `src/data/media-manifest.json`
- relatório de faltantes
- URLs de teste

Critério de aprovação:
- Imagens referenciadas respondem 200 no R2.
- Nenhum link para `i0.wp.com`.
- Peso dentro do plano.

Status: **[x] concluída — aprovada pelo usuário**
Aprovação do usuário: **aprovada em 2026-10-22; 2.129 placeholders autorizados**

Notas da execução:
- Script: `src/scripts/media.py` (`scan`, `resolve`, `extract`, `wayback`, `process`, `report`); `dados/midia/` é privado e está no `.gitignore`.
- Backup: 86.508 entradas; 59.742 uploads; 3.159 arquivos extraídos (~1,56 GB), incluindo 66 fontes de galeria extraídas sob demanda.
- Referências: 5.143 (5.027 originais + 116 de featured/galeria); 3.014 resolvidas; 2.129 placeholders.
- O diretório `uploads/2014/` existe apenas como `.listing` no tar; as imagens de 2014 não estão no backup. O Wayback tinha 636 correspondências exatas, mas o acesso foi bloqueado por HTTP 429; 3 arquivos foram recuperados.
- Saída local: 12.275 arquivos, 1,80 GB; 2.129 placeholders (~107 MB); nenhuma falha de processamento.
- `media-manifest.json`: 5.114 entradas; fallback no caminho original e WebP por largura.
- Integração no build: `picture`/`srcset` para destaques, cards e conteúdo; `manifest` ativado automaticamente quando `media_base` é o R2, com `--force-manifest` para QA local.
- `site.json`: `media_base` definido como `https://media.cinemaemuitomais.com/wp-content/uploads`; as chaves do bucket preservam `wp-content/uploads/ano/mes/arquivo`.
- Integridade do manifest: 5.114 entradas, 2.129 placeholders, **0 assets ausentes** (fallback + 4 WebP verificados com suporte a caminhos longos do Windows).
- 6 arquivos têm caminho absoluto >260 caracteres; o Windows exige `\\?\` para acessá-los. O upload usa essa forma; o R2 não tem essa limitação.
- Corrigido: URLs externas com `/wp-content/uploads/` (ex.: `supernovo.net`) não são mais concatenadas; sufixos `-scaled`/`-rotated` são reconhecidos.
- Corrigido: o rewrite relativo não reprocessa URLs que já apontam para o `media_base`; isso eliminava URLs duplicadas como `https://media...https//media...`.
- Corrigido: `site.json` e o prefixo do bucket preservam `/wp-content/uploads/`.
- Upload R2 concluído em 2026-10-21 (19:48–20:14): bucket `cmm-media`, prefixo `wp-content/uploads/`, 12.275 arquivos / 1.803.938.996 bytes.
- Relatório de upload: 12.270 enviados, 5 ignorados por já existirem, **0 falhas**; verificação do script: **12.275/12.275 OK** (`dados/midia/upload-report.json`).
- Auditoria independente por HTTP: **12.275/12.275 URLs públicas responderam 200**, incluindo as 5.114 entradas do manifest e todos os WebP.
- Domínio `media.cinemaemuitomais.com` ativo no R2; teste real em `/wp-content/uploads/2020/12/hilary-duff-lizzie-hair.jpg` e `.w400.webp` retornou 200.
- Cache: `Cache-Control: public, max-age=31536000, immutable`; GET repetido retornou `cf-cache-status: HIT`.
- Sample com produção (`dados/preview-r2`): 432 arquivos, 5,9 MB; 346 URLs de mídia, todas 200; 0 `i0.wp.com`; 0 URL de upload externa concatenada; 0 URL duplicada.
- **Hotlink Protection desativado para o host `media.cinemaemuitomais.com`** via Configuration Rule (`http.host eq "media.cinemaemuitomais.com"`). Testes com Referer Google, Bing, Facebook, localhost e `www` retornaram 200.
- Auditoria final com `Referer: https://www.google.com/`: **12.275/12.275 URLs 200**, 0 falhas.
- QA visual final (Chrome/Puppeteer, produção):
  - home: 25/25 imagens carregadas em 390 px e 1440 px;
  - post: 6/6 imagens carregadas em 390 px e 1440 px;
  - 0 erros de console, 0 requisições falhas, 0 overflow horizontal.
- Critérios de aprovação atendidos: imagens 200 no R2, nenhum `i0.wp.com`, 1,80 GB dentro do plano.
- Limitação remanescente: 2.129 placeholders continuam necessários porque os originais de 2014 não existem no backup e o Wayback está bloqueado por 429.

---

### Fase 5 — Geração completa do site

**Objetivo:** gerar todas as páginas estáticas.

Tarefas:
- [x] Home estática.
- [x] 4.596 posts + 191 páginas.
- [x] Tags: 14.930 bases page 1 (14.847 no sitemap) + 15.277 páginas com paginação; 1.692 vazias omitidas.
- [x] 8 categorias com paginação (97 páginas).
- [x] Autores (5 autores, 95 páginas).
- [x] Busca Pagefind em `/busca/`.
- [x] `404.html`.
- [x] Sitemaps estáticos.
- [x] `robots.txt`, `ads.txt`, `llms.txt`, favicons, manifest.
- [x] `CNAME` e `.nojekyll`.

Entregáveis:
- `site/` completo
- sitemaps
- relatório de contagem por tipo em `dados/fase5-relatorio.md`

Critério de aprovação:
- Contagem de páginas confere com o plano.
- Tamanho total < 1 GB.
- Sitemaps válidos.

Status: **[x] concluída — aprovada pelo usuário**
Aprovação do usuário: **aprovada em 2026-10-22**

Notas da execução:
- Comando: `python src/scripts/build.py --all --pagefind`.
- Saída: `site/`, 25.280 arquivos, 20.258 HTML, **336,0 MB (0,328 GB)**, 675 s.
- Conteúdo: 4.596 posts, 191 páginas (incluindo home), 14.930 bases de tags, 8 categorias, 5 autores.
- Arquivos: 15.277 páginas de tag, 97 de categoria, 95 de autor, busca e 404.
- Pagefind: ok; 4.786 páginas indexadas, 57.070 palavras, índice em `/pagefind/` e UI em `/busca/`; teste real com “Tarantino” retornou 41 resultados.
- Sitemaps: `post-sitemap.xml` (4.596), `page-sitemap.xml` (191), `post_tag-sitemap.xml` (14.847), `category-sitemap.xml` (8), `author-sitemap.xml` (5); total **19.647 URLs** validadas, sem duplicatas e com todos os arquivos no disco.
- Índice em `sitemap_index.xml`; alias em `sitemap.xml`; `robots.txt` aponta para o índice.
- Publicação: `CNAME` (`www.cinemaemuitomais.com`), `.nojekyll`, `ads.txt` (`pub-6725457701341059`), `llms.txt`, `site.webmanifest`, favicons e apple-touch-icon.
- A contagem de 15.076 do plano era de bases de arquivo do crawl; a fonte de verdade para tags é o Yoast (14.847 no sitemap) e o banco de tags (14.930 bases, incluindo 3 vazias no sitemap).
- 1.692 tags vazias fora do sitemap e 2 categorias vazias/noindex foram omitidas.
- Tokens de verificação Google/Bing/Yandex não foram fornecidos; `site.json.verification` já é suportado e a validação pode ser feita por DNS/GSC na Fase 7.
- 2.129 placeholders de mídia ausente foram mantidos conforme aprovação da Fase 4.
- `site/` é saída gerada e continua no `.gitignore`.

---

### Fase 6 — QA local

**Objetivo:** validar tudo antes do deploy.

Tarefas:
- [x] Crawler local em todas as URLs.
- [x] Nenhum 404 interno.
- [x] Imagens/assets 200.
- [x] Conferir title/description/canonical/og/JSON-LD.
- [x] Testar busca, menu mobile, paginação, consentimento, AdSense e GA4.
- [x] Testar redirects e 404.
- [x] Lighthouse:
  - mobile ≥ 85
  - desktop ≥ 95
  - LCP < 2,5 s
  - JS < 200 KB
- [x] Medir tamanho; tempo de deploy será medido na Fase 7.

Entregáveis:
- `dados/qa-relatorio.md`
- screenshots de Lighthouse
- lista de correções

Critério de aprovação:
- Zero erros críticos.
- Metas de performance atingidas ou justificadas.
- Consentimento funcionando.

Status: **[x] concluída — aguardando aprovação**

Notas da execução:
- 25.280/25.280 arquivos com HTTP 200; 0 links internos quebrados e 0 links sem barra final.
- 12.023 referências de mídia R2 com 200; 25 URLs 404 substituídas pelo placeholder aprovado.
- SEO: 0 H1 inválido, 0 canonical divergente, 0 title/description/robots ausentes, 0 JSON-LD inválido.
- Avisos não críticos: 16.399 `og:image` ausentes; 17 títulos duplicados; 9.105 descrições curtas; 1.571 títulos longos.
- Sitemaps: 19.647 URLs válidas; 83 tags `noindex` fora do sitemap.
- Funcional: consentimento bloqueia GA4/AdSense até o aceite; GA4, AdSense, busca (41 resultados), menu e paginação validados.
- Redirects: 7.141 regras sem destinos ausentes, conflitos ou cadeias; 410 não gerados.
- Lighthouse: mobile 95 / desktop 100; LCP 2,4 s / 0,7 s; JS 10,1 KB.
- Relatório completo: `dados/qa-relatorio.md`; execução e avisos restantes documentados.
- GTM-WTDZX43 permanece configurado, mas o site usa GA4 direto e não injeta o container GTM.

---

### Fase 7 — Deploy, Cloudflare e corte

**Objetivo:** colocar no ar e desligar o WordPress com segurança.

Tarefas:
- [x] Criar repositório GitHub e workflow de deploy.
- [x] Publicar GitHub Pages.
- [x] Configurar domínio `www.cinemaemuitomais.com`.
- [x] HTTPS na borda Cloudflare; GitHub Pages permanece como origem, sem domínio personalizado.
- [x] Cloudflare:
  - apex → 301 para `www`;
  - `www` → GitHub Pages com proxy;
  - `media` → R2;
  - SSL Full (strict);
  - Always Use HTTPS;
  - Worker/Bulk Redirects.
- [x] Testar HTTPS, apex/www, redirects, 404, imagens, AdSense e GA4.
- [ ] Reenviar sitemap no GSC.
- [ ] Monitorar 404/cobertura por 30 dias.
- [ ] Só depois cancelar a hospedagem antiga.
- [ ] Configurar e-mail na v2.0.

Entregáveis:
- site em produção
- checklist de corte
- relatório de monitoramento inicial

Critério de aprovação:
- Produção estável.
- HTTPS válido.
- URLs principais e P0 respondendo 200.
- Redirects funcionando.
- Autorização do usuário para cancelar a hospedagem.

Status: **[x] concluída e aprovada pelo usuário — web publicada; monitoramento e e-mail pendentes**
Aprovação do usuário: **aprovada em 2026-10-23**

### Execução em 2026-10-23

- Relatório local: `dados/fase7-relatorio.md`.
- Repositório: `https://github.com/gabrielgpacheco/site-estatico-cmm`. O repositório raiz `gabrielgpacheco.github.io` não foi usado.
- GitHub Pages: `https://gabrielgpacheco.github.io/site-estatico-cmm/`, publicado pelo workflow `.github/workflows/pages.yml`. O `CNAME` é removido do artefato.
- Cloudflare Worker `cmm-static-proxy`, rotas `www.cinemaemuitomais.com/*` e `cinemaemuitomais.com/*`; o Worker reescreve a origem para o caminho do Pages de projeto.
- DNS:
  - `www` → CNAME `gabrielgpacheco.github.io`, proxied;
  - apex → quatro A do GitHub Pages, proxied;
  - `media` preservado em R2;
  - SSL Full (strict) e Always Use HTTPS já estavam ativos.
- Snapshot do DNS anterior: `dados/fase7-dns-antes.json`.
- Validação:
  - 20.285 arquivos estáticos responderam 200 em produção, excluindo os arquivos com hash do Pagefind;
  - 7.141 regras de redirect validadas (301/410);
  - sitemaps com 19.647 URLs;
  - busca Pagefind com 41 resultados para “tarantino”;
  - consentimento bloqueia GA4 antes do aceite e libera GA4 depois;
  - apex e HTTP redirecionam para `https://www.cinemaemuitomais.com/`;
  - 404 customizado e mídia R2 operacionais.
- Pendências:
  - reenvio do sitemap no GSC;
  - monitoramento de 404/cobertura por 30 dias;
  - **e-mail: configuração adiada para a v2.0 por decisão do usuário**;
  - não cancelar a hospedagem antiga enquanto o e-mail não for tratado;
  - regra explícita de cache para HTML/uploads ainda não criada; o comportamento padrão da Cloudflare está ativo.
- O workflow emite avisos de depreciação do Node.js 20 nas actions; não bloqueiam o deploy.

### Revisão de identidade visual (pós-Fase 7)

Status: **[x] concluída e aprovada pelo usuário — publicada em produção**
Data: 2026-10-23 (implementação) / 2026-10-24 (publicação)

Entregue:
- Originais preservados em `dados/identidade/` (PSD e PNG transparente); pasta ignorada pelo Git.
- Cores amostradas da marca: grafite `#2D2D2D`, teal `#00475B`, lima `#A3CE4B`.
- Header e footer usando somente a logomarca, sem wordmark adicional; nome oficial “Cinema e Muito +” preservado em metadados, alt e rodapé.
- Logo exportada em WebP e PNG (240 px) com disco grafite no CSS; header 80 px / mobile 64 px; footer 120 px / mobile 96 px.
- Novo favicon SVG/ICO/PNG e ícones PWA 192, 512 e maskable, com símbolo simplificado.
- Paleta aplicada em links, botões, navegação, Pagefind, seleção, foco, tags e rodapé; vermelho mantido apenas como cor semântica de perigo.
- `theme-color` e manifest atualizados para `#00475B`.
- Sem alterações em conteúdo, URLs, GA4, AdSense, consentimento ou schema.

Validação:
- Build completo: 20.257 HTML, 25.283 arquivos, 342,2 MB; Pagefind com 4.786 páginas.
- Amostra de 250 HTML: 100% com a nova logo/favicon/tema; nenhuma referência ao vermelho antigo.
- Todos os assets locais referenciados na amostra existem.
- Screenshots locais em 1440, 1280, 1024, 768 e 390 px; sem overflow no header.
- Contraste: teal sobre branco 10,23:1; lima sobre grafite 7,53:1; lima sobre `#141414` 10,08:1.

Publicação:
- Aprovação visual do usuário em 2026-10-24.
- Commit `8f3dc55` (`Atualiza identidade visual do site`) enviado para `main`.
- Workflow GitHub Actions `40056615848` concluído com sucesso.
- Produção validada em `www.cinemaemuitomais.com`, apex e Pages direto: logo, tema, favicon e manifest novos, sem referências ao vermelho antigo.
- Assets novos, CSS e Pagefind respondendo 200.
- Correção pós-publicação em 2026-10-24: removido o disco cinza da logo (`background: transparent`), CSS versionado em `main.css?v=3`, commit `66de688` e workflow `40366718414` concluído com sucesso.
- Produção revalidada após a correção, inclusive em 1440 e 390 px; sem `brand-dark` no CSS.
- Pendente de cache Cloudflare: HTML e assets retornam `cf-cache-status: HIT` com `max-age=345600`; o cache level está `aggressive`. O token atual não tem permissão para Cache Rules nem Purge, então é necessário liberar essas permissões ou ajustar pelo dashboard.

---

## 9. Critérios de aceite finais

- [ ] Todos os 4.787 posts/páginas acessíveis.
- [ ] Todas as tags com tráfego acessíveis.
- [ ] Nenhum link interno quebrado.
- [ ] Imagens referenciadas respondendo no R2.
- [ ] Meta/SEO preservados do Yoast.
- [ ] Canonical sem `localhost`.
- [ ] Site publicado ≤ 1 GB.
- [ ] Mídia fora do GitHub.
- [ ] GA4/AdSense bloqueados antes do consentimento.
- [ ] GSC sem queda brusca de cobertura.
- [ ] 404s antigos redirecionados.

---

## 10. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| GA4 poluído por bot | Priorizar GSC; conferência manual dos P0 |
| 2.160 mídias faltantes | 2.129 receberam placeholder; recuperar 2014 exige outro backup ou Wayback |
| Caminhos Windows >260 caracteres | Upload e scripts usam prefixo `\\?\`; R2 não tem essa limitação |
| Shortcodes/embeds antigos | Amostragem por década; correção manual nos problemáticos |
| Limite de 1 GB no Pages | Tema leve, tags mínimas, mídia no R2, medir desde a Fase 3 |
| Build > 10 min | Build local e branch `gh-pages` se necessário |
| AdSense/consentimento | Banner próprio + Consent Mode v2; manter políticas |
| Segredos no backup | Nunca commitar dumps; rotacionar chaves após o corte |
| Perda de SEO | URLs idênticas, canonicals do Yoast, sitemaps e redirects |
| E-mail no cPanel | **Adiado para a v2.0**; não cancelar a hospedagem antiga antes de migrar MX, IMAP/SMTP, SPF/DKIM/DMARC e testar envio/recebimento |

### Pendências para a v2.0

- Configurar o e-mail do domínio; a decisão de 2026-10-23 foi ignorar o tema nesta entrega.
- Não cancelar a hospedagem antiga enquanto o e-mail não estiver migrado ou desativado conscientemente.
- Reenviar o sitemap no GSC e acompanhar cobertura/404 por 30 dias.
- Avaliar regras explícitas de cache para HTML e uploads, se necessário.

---

## 11. Ao retomar no dia seguinte

1. Ler este arquivo inteiro.
2. Verificar qual fase está marcada como “em andamento” ou “não iniciada”.
3. Confirmar com o usuário: **“Posso executar a Fase X?”**
4. Executar **somente** a fase autorizada.
5. Ao final, atualizar este arquivo com status e resultados.
6. Apresentar o resultado e aguardar aprovação antes da próxima fase.

**Nunca executar duas fases seguidas sem aprovação.**
