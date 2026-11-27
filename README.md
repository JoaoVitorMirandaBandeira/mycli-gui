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
