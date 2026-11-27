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

Prefere o terminal? `my -a` faz a mesma pergunta por lá. Quer trazer as do DBeaver? Rode `python3 tools/import_dbeaver.py`.

Depois escolha o banco no topo, clique numa tabela à esquerda ou escreva a consulta e aperte **Ctrl+Enter**.

Para alterar registros, abra uma tabela pela lista à esquerda e clique em **Editar dados**. Clique na célula, digite o novo valor e pressione **Enter**. Use o botão **NULL** da célula para gravar um valor nulo. Quando terminar, clique em **Salvar** para aplicar todas as alterações ou em **Descartar** para desfazê-las antes de gravar.

A edição direta fica disponível para tabelas InnoDB com chave primária visível e colunas compatíveis. Chaves primárias, colunas geradas e resultados de SQL escrito no editor são somente leitura. Se um registro tiver mudado desde a consulta, o MySQL desfaz o lote e a interface pede para recarregar a tabela.

### Chaves estrangeiras

Ao abrir uma tabela pela lista à esquerda, as colunas que são chave estrangeira (FK) ganham o selo **FK** no cabeçalho (passe o mouse para ver a coluna referenciada e as regras `ON DELETE`/`ON UPDATE`). Passe o mouse sobre o valor de uma FK e clique no **↗** que aparece: o registro referenciado abre na própria aba (`SELECT * FROM tabela_ref WHERE chave = valor`). **Ctrl+clique** no ↗ abre em uma nova aba.

Para voltar ao resultado de onde você veio (com a posição da rolagem e a linha selecionada), use o botão **← Voltar** no topo do resultado ou **Alt+←**; dá para encadear vários saltos e voltar um por um. Valores `NULL` não têm ↗. Funciona também no modo **Vertical** e no painel do registro. As FKs de cada tabela são buscadas sob demanda, numa única consulta leve ao `information_schema`, e ficam em cache até você recarregar (**⟳**) ou alterar tabelas.

Se você tiver alterações pendentes de edição, o salto pede confirmação antes de descartá-las.

## O que fica salvo

Ao fechar e abrir de novo (ou reiniciar a máquina) a janela volta como estava: **conexão e banco de cada conexão, abas, SQL escrito e histórico**. Fica em `~/.config/my-gui/state.json` (permissão 600, gravação atômica com `fsync` e cópia `.bak`).

## Dicas

| Quero | Como |
|---|---|
| Ver um registro "em pé" (como `\G`) | botão **Vertical** no resultado |
| Sugestões de tabela/coluna | digite; ou **Ctrl+Espaço** |
| Executar só um trecho | selecione e **Ctrl+Enter** |
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
