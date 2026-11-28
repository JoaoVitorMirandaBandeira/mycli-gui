# my — MySQL leve

Um comando só, `my`, para consultar seus bancos MySQL sem abrir um DBeaver pesado:

- **`my`** abre uma janela gráfica leve (editor SQL com cores e autocomplete, resultado em tabela).
- **`my nome`** abre o mycli no terminal, já conectado.

## Instalar (Ubuntu/Debian)

```bash
git clone https://github.com/JoaoVitorMirandaBandeira/mycli-gui.git
cd mycli-gui
./install.sh
```

O `install.sh` instala o que faltar (`mycli`, `python3-pymysql`; pede sua senha de administrador), copia os arquivos para `~/.local` e cria o atalho **"my — MySQL"** no menu de aplicativos.

## Usar

**1. Abra a janela:**

```bash
my
```

**2. Adicione sua conexão** (só na primeira vez): clique em **＋** ao lado da lista de conexões, preencha nome, host, porta, usuário e senha, clique em **Testar** e depois em **Salvar**. Para mudar ou apagar uma conexão use o **✎**.

Prefere o terminal? `my -a` faz a mesma pergunta por lá. O SSL é por conexão (caixa **Usar SSL**, ou `?ssl=true` no alias do `~/.myclirc`); desmarcado, o `my` roda o mycli com `--ssl-mode off`, que é o padrão para evitar o erro dos mycli novos com servidores sem SSL. Quer trazer as do DBeaver? Rode `python3 tools/import_dbeaver.py`.

Depois escolha o banco no topo, clique numa tabela à esquerda ou escreva as consultas no editor, separadas por ponto e vírgula. **Ctrl+Enter**, **F5** e o botão **Executar** rodam o trecho selecionado ou, sem seleção, a consulta sob o cursor. Use **Ctrl+Shift+Enter** para executar o script inteiro.

Em linhas vazias ou de comentário entre consultas, o editor usa a consulta anterior. Se o cursor estiver antes de todas elas, usa a primeira.

Para recolher uma consulta de várias linhas, clique na seta ao lado do número da primeira linha. Clique na seta novamente ou nas reticências para expandir.

Em scripts acima de 300 mil caracteres, o recolhimento e o autocomplete ficam indisponíveis para manter a digitação responsiva. Os atalhos de execução continuam disponíveis.

Ao criar procedures, funções, triggers ou eventos, declare um delimitador como `DELIMITER $$` em uma linha própria. Termine a definição com `$$` e use `DELIMITER ;` para voltar ao padrão. O mesmo vale para blocos `BEGIN NOT ATOMIC` do MariaDB. Assim, os pontos e vírgulas do corpo fazem parte da definição.

Para alterar registros, abra uma tabela pela lista à esquerda ou execute um `SELECT *` de uma única tabela, inclusive com `WHERE`, `ORDER BY` e `LIMIT`. Dê um duplo clique na célula ou clique em **Editar dados** e escolha a célula. Digite o novo valor e pressione **Enter**. Use o botão **NULL** da célula para gravar um valor nulo. Quando terminar, clique em **Salvar** para aplicar todas as alterações ou em **Descartar** para desfazê-las antes de gravar.

A edição direta fica disponível para tabelas InnoDB com chave primária visível e colunas compatíveis. Chaves primárias e colunas geradas são somente leitura. Em resultados com **Somente leitura**, clique nesse botão para ver o motivo. Se um registro tiver mudado desde a consulta, o MySQL desfaz o lote e a interface pede para recarregar a tabela.

Para levar o SQL das alterações pendentes para outro editor, clique em **Copiar UPDATE**. Cada comando inclui o banco, a tabela e a chave primária original da linha.

### Banco de demonstração

Para experimentar o plano de execução e as sugestões sem mexer nos seus bancos, há um MySQL 8.4 de demonstração em Docker, com dados montados para disparar cada diagnóstico:

```bash
tools/demo-db/demo-db.sh
```

O script cria o container `my-gui-demo` (só em `127.0.0.1:3398`), carrega uns 670 mil registros em cerca de 15 segundos e pergunta se pode adicionar a conexão `demo` ao `~/.myclirc`. As consultas de teste, com o que esperar de cada uma, ficam em `tools/demo-db/consultas.sql`. Use `demo-db.sh down` para apagar tudo e `demo-db.sh reset` para recriar do zero. Para só desligar e manter os dados: `docker stop my-gui-demo`.

### Chaves estrangeiras

Ao abrir uma tabela pela lista à esquerda — ou ao executar um `SELECT` simples de uma só tabela (sem `JOIN`, `GROUP BY`, funções ou `AS`) — as colunas que são chave estrangeira (FK) ganham o selo **FK** no cabeçalho (passe o mouse para ver a coluna referenciada e as regras `ON DELETE`/`ON UPDATE`). Passe o mouse sobre o valor de uma FK e clique no **↗** que aparece: o registro referenciado abre na própria aba (`SELECT * FROM tabela_ref WHERE chave = valor`). **Ctrl+clique** no ↗ abre em uma nova aba.

Para voltar ao resultado de onde você veio (com a posição da rolagem e a linha selecionada), use o botão **← Voltar** no topo do resultado ou **Alt+←**; dá para encadear vários saltos e voltar um por um. Valores `NULL` não têm ↗. Funciona também no modo **Vertical** e no painel do registro. As FKs de cada tabela são buscadas sob demanda, numa única consulta leve ao `information_schema`, e ficam em cache até você recarregar (**⟳**) ou alterar tabelas.

Se você tiver alterações pendentes de edição, o salto pede confirmação antes de descartá-las.

### Plano de execução (Visual Explain)

Pressione **Ctrl+E** para ver como o MySQL pretende executar a seleção ou a consulta sob o cursor. O app usa `EXPLAIN FORMAT=JSON`, que **não executa** a consulta, então funciona também com `UPDATE`, `DELETE` e `INSERT … SELECT`.

- **Diagrama**: lê-se de baixo para cima, como no MySQL Workbench. Cada tabela é uma caixa colorida pelo tipo de acesso: azul (linha única), verde (busca por chave), laranja (faixa de índice) e vermelho (varredura completa). Os JOINs aparecem como losangos, e a espessura das setas acompanha o número de linhas. Tabelas derivadas e subqueries ficam em molduras tracejadas.
- **Diagnósticos**: os cartões no topo apontam varreduras completas, filesort, tabela temporária, subquery dependente e JOIN sem índice, do mais grave para o mais leve. Quando dá, sugerem um `CREATE INDEX`, com botões para copiar ou abrir numa aba nova. Confira os índices que já existem antes de criar.
- **Sugestões de reescrita**: a aba **Sugestões** mostra a consulta atual ao lado de uma versão reescrita, quando o plano revela um padrão conhecido: subquery correlacionada com agregação (vira `LEFT JOIN` com a agregação pré-calculada), `DATE()`/`YEAR()` sobre a coluna no `WHERE` (vira uma faixa que usa o índice) e coluna de texto comparada com número (aviso 1739 do servidor). Cada reescrita é conferida com `EXPLAIN` e só ganha destaque se o custo estimado cair. Como as estimativas erram, principalmente com tabelas derivadas, o botão **⏱ Medir de verdade** executa as duas versões com `EXPLAIN ANALYZE` (só para `SELECT`, depois de confirmar; as linhas não são trazidas) e compara o tempo real. Confira o resultado da consulta nova antes de trocar a original.
- **Ordem do JOIN**: em JOINs no MySQL 8.0+, a aba **Sugestões** também traz ordens alternativas de leitura das tabelas, forçadas com o hint `JOIN_ORDER`. O otimizador escolhe a ordem de menor custo *estimado*; quando a estimativa erra, outra ordem pode ser bem mais rápida, e só a medição real decide. Use **⏱ Medir todas de verdade** para comparar o tempo da consulta atual com todas as alternativas de uma vez.
- **Diagnósticos do plano**: além do que aparece no SQL, o app lê o plano para apontar índices na coluna de junção (tabelas internas do JOIN, hash join e subqueries dependentes) e **estimativas chutadas**: quando o `filtered` é um valor padrão do MySQL (10%, 11,11%, 33,33%), falta índice ou histograma naquela coluna, e o app sugere o `ANALYZE TABLE … UPDATE HISTOGRAM`.
- **Conselhos**: os diagnósticos também apontam `OFFSET` grande (com o modelo de paginação por chave), índice para `ORDER BY … LIMIT` e `LIKE` começando com `%` (com o modelo de índice `FULLTEXT`).
- **Detalhes**: clique num nó para ver índice usado e possíveis, linhas, custo, a parte do custo total e a condição aplicada. Dê um duplo clique para achar a tabela no editor. O painel mostra também como o MySQL interpretou a consulta (`SHOW WARNINGS`), já formatada e com cores. Não é uma versão otimizada: é a mesma consulta depois das transformações internas, e gera o mesmo plano.
- **Outras visões**: **Árvore** (tabela com barras de custo), **Tabela** (o `EXPLAIN` tradicional) e **JSON** (a saída bruta). Em **cor**, troque o tipo de acesso por **% do custo** para achar os pontos quentes.
- Navegue com a roda do mouse (zoom), arrastando (mover) e com **F** (ajustar à tela). O botão **⤓** salva o diagrama em SVG.

Testado com MySQL 8.4; o formato JSON usado é o mesmo desde o 5.7. No 8.3 ou mais novo, o app pede o formato JSON v1 só durante o EXPLAIN e devolve a configuração da sessão depois. O formato do MariaDB é diferente e é lido com tolerância, mas ainda não foi testado num servidor MariaDB real.

## O que fica salvo

Ao fechar e abrir de novo (ou reiniciar a máquina) a janela volta como estava: **conexão e banco de cada conexão, abas, SQL escrito e histórico**. Fica em `~/.config/my-gui/state.json` (permissão 600, gravação atômica com `fsync` e cópia `.bak`).

## Atualizações

A janela mostra a versão instalada (`v1.0.0`, no topo à direita) e, quando há uma release nova no GitHub, o botão verde **⬆ Atualizar para vX.Y.Z**. Clique nele: o app baixa a versão, instala em `~/.local` e recarrega a janela sozinho (abas, SQL e histórico continuam como estavam). Se houver alterações pendentes na tabela, ele pede para salvar ou descartar antes. Clicar no número da versão força uma verificação.

- A verificação roda ao abrir o app e a cada 6 horas, em segundo plano: uma requisição leve à API de releases (com ETag; sem rede ou com a VPN fora, simplesmente não avisa).
- Segurança: só baixa por HTTPS de `github.com/JoaoVitorMirandaBandeira/mycli-gui` (redirecionamentos só para o CDN do GitHub), confere o SHA-256 publicado na release e copia apenas `bin/my`, `server.py`, `index.html`, `my-gui.svg` e `VERSION`. Nada do pacote é executado, nem o `install.sh`. A rota de atualização exige o token da sessão, como as demais.
- A versão anterior fica em `~/.local/share/my-gui/backup/`. Se a versão nova não subir, o app volta sozinho para a anterior. Para voltar manualmente: `python3 ~/.local/share/my-gui/server.py --rollback` (e abra `my` de novo).
- A atualização não instala dependências nem refaz o atalho do menu; se uma versão pedir isso, rode `git pull && ./install.sh`. Cópias fora de `~/.local` (checkout de desenvolvimento) não se atualizam sozinhas.

### Publicar uma versão nova (mantenedor)

1. Aumente o número em `my-gui/VERSION` (ex.: `1.1.0`), faça commit e merge na `main`.
2. Na `main` atualizada, com o `gh` logado: `tools/release.sh "o que mudou"` (sem texto, as notas são geradas dos commits).

O script cria a tag `v1.1.0` e a release com `my-gui-1.1.0.tar.gz` e o `.sha256`; em até 6 horas (ou ao reabrir o app) os usuários veem o aviso. O `VERSION` precisa ser maior que o da release anterior, e o app ignora releases sem esses dois arquivos.

### Desenvolver o editor SQL

O bundle do editor fica em `my-gui/index.html` para que o aplicativo funcione offline e seja compatível com o atualizador. Depois de alterar suas dependências ou exports, rode `npm ci --prefix tools/sql-editor` e `npm run build --prefix tools/sql-editor`. Confira o bundle com `npm run check --prefix tools/sql-editor`.

Os testes do parser e do plano de execução rodam com `node --test tests/sql-editor.test.cjs tests/plan.test.cjs tests/format.test.cjs tests/rewrite.test.cjs` e `python3 -m unittest discover -s tests`.

## Dicas

| Quero | Como |
|---|---|
| Ver um registro "em pé" (como `\G`) | botão **Vertical** no resultado |
| Copiar o valor de uma célula | **Ctrl+clique** na célula do resultado |
| Sugestões de tabela/coluna | digite; ou **Ctrl+Espaço** |
| Executar só um trecho | selecione e **Ctrl+Enter** |
| Ver o plano de execução | **Ctrl+E** (não executa a consulta) |
| Formatar SQL | **Ctrl+Shift+F** (seleção ou consulta sob o cursor; desfaz com Ctrl+Z) |
| Ver todos os atalhos | **F1** ou o botão **⌨** no topo |
| Nova aba / fechar aba | **Ctrl+T** / **Ctrl+W** (ou **Alt+N** / **Alt+W**) |
| Reabrir a última aba fechada | **Ctrl+Shift+T** |
| Trocar de aba | **Ctrl+Tab** / **Ctrl+Shift+Tab**, ou **Ctrl+1…9** |
| Comentar/descomentar linha | **Ctrl+/** |
| Histórico de consultas | **Alt+H** |
| Terminal em vez de janela | `my nome_da_conexao` |
| Nova / editar conexão | **＋** e **✎** na janela (ou `my -a`) |
| Listar conexões | `my -l` |

A janela usa um perfil do Chrome só dela (`~/.config/my-gui/chrome`), isolado das suas extensões e logins; é isso que faz o ícone aparecer certo no dock.

As conexões ficam no `~/.myclirc` (permissão 600). As senhas nunca vão para a página, e o servidor só aceita conexões da própria máquina (`127.0.0.1`).

## Problemas comuns

- **`my: command not found`** — abra um terminal novo (o instalador adicionou `~/.local/bin` ao PATH).
- **Não conecta** — confira VPN/rede e o host/porta com `my -l`; o erro aparece no topo da janela.
- **Log da janela:** `~/.cache/my-gui/log`.
