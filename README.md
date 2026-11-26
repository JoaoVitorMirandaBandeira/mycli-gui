# my — MySQL leve para o dia a dia

Um atalho único (`my`) para trabalhar com vários MySQL **sem abrir um DBeaver pesado**:

- `my` abre uma **janela gráfica leve** (servidor Python local + janela do Chrome em modo app).
- `my <conexão>` abre o **mycli** no terminal, já conectado.
- As conexões vêm de um só lugar: os aliases `[alias_dsn]` do `~/.myclirc`.

## Interface gráfica (`my-gui`)

- Conexão e banco no topo; árvore de tabelas à esquerda (clique = `SELECT * … LIMIT 200`, ⓘ = `DESCRIBE`).
- Editor SQL com **destaque de sintaxe** e **autocomplete** de tabelas, colunas (inclusive por alias, `j.`), bancos, palavras-chave e funções. `Ctrl+Espaço` força a sugestão.
- Abas, histórico (`Alt+H`), vários comandos separados por `;` (um resultado para cada).
- Resultado: cabeçalho fixo, ordenar por coluna, filtro de texto, **visão vertical** (equivale ao `\G`), painel do registro, copiar valor (duplo clique), exportar CSV.
- Confirmação antes de `DROP`, `TRUNCATE` e `DELETE`/`UPDATE` sem `WHERE`.

Atalhos: `Ctrl+Enter`/`F5` executa (ou só a seleção) · `Alt+N` nova aba · `Alt+W` fecha aba · `Alt+H` histórico.

### Segurança

- O servidor escuta **só em `127.0.0.1`**, numa porta aleatória, com token por sessão (e valida `Host`).
- As senhas ficam no `~/.myclirc` (permissão 600) e **nunca vão para a página**.
- O processo encerra sozinho quando a janela é fechada.

## Instalação

Requisitos: Linux, `python3`, `python3-pymysql`, `mycli`, Google Chrome/Chromium (sem Chrome ele abre o navegador padrão).

```bash
sudo apt install mycli python3-pymysql      # se ainda não tiver
./install.sh
```

Instala `~/.local/bin/my`, os arquivos em `~/.local/share/my-gui/`, o ícone e o atalho “my — MySQL” no menu de aplicativos.

## Conexões

Adicionar uma nova:

```bash
my -a              # pergunta nome, host, porta, usuário e senha
```

ou edite o `~/.myclirc`:

```ini
[alias_dsn]
producao = mysql://usuario:senha@10.0.0.5:3306/
```

(caracteres especiais na senha precisam de escape: `@`→`%40`, `:`→`%3A`, `/`→`%2F`, `#`→`%23`.)

Importar do DBeaver:

```bash
python3 tools/import_dbeaver.py
```

## Comandos

| Comando | O que faz |
|---|---|
| `my` / `my -g [alias]` | abre a janela gráfica (opcionalmente já numa conexão) |
| `my alias [banco]` | abre o mycli no terminal |
| `my -m` | menu de conexões no terminal |
| `my -a` | adiciona uma conexão |
| `my -l` | lista as conexões |

## Notas

- O mycli 1.54 tem `-d alias` quebrado; o `my` passa o alias posicional.
- O launcher usa `--ssl-mode off`: os servidores de origem derrubavam a conexão com SSL. Ajuste em `bin/my` se o seu servidor exigir SSL.
- Log da interface: `~/.cache/my-gui/log`.
