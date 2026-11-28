-- Consultas para testar o plano de execução no banco de demonstração.
-- Ponha o cursor numa consulta e aperte Ctrl+E. A aba "Sugestões" mostra as reescritas e as
-- alternativas de plano; "⏱ Medir de verdade" executa (só leitura) e compara o tempo real.

-- 1. Subquery correlacionada → LEFT JOIN agrupado.
--    pagamentos.pedido_id não tem índice: a subquery varre 100 mil linhas para cada pedido.
--    Espere: reescrita "Subquery correlacionada vira JOIN" e índice sugerido em pagamentos (pedido_id).
SELECT p.id, p.valor
FROM pedidos p
WHERE p.id <= 100
  AND p.valor > (SELECT SUM(pg.valor) FROM pagamentos pg WHERE pg.pedido_id = p.id);

-- 2. Ordem do JOIN + estimativa chutada.
--    O MySQL acha que 10% dos clientes são de SP (são 95%) e começa por clientes.
--    Espere: "Estimativa chutada" com o histograma e a alternativa "Começar o JOIN por pedidos".
--    Meça as duas; depois rode o ANALYZE TABLE … UPDATE HISTOGRAM sugerido e explique de novo.
SELECT c.nome, p.id, p.valor
FROM clientes c
JOIN pedidos p ON p.cliente_id = c.id
WHERE c.uf = 'SP'
  AND p.status = 'estornado';

-- 3. Função sobre a coluna → faixa (usa o índice ix_pedidos_criado).
SELECT id, valor
FROM pedidos
WHERE DATE(criado_em) = '2024-06-15';

SELECT COUNT(*)
FROM pedidos
WHERE YEAR(criado_em) = 2024;

-- 4. Texto comparado com número (aviso 1739): o índice uk_clientes_cpf é ignorado.
--    Repare no aviso da sugestão: aqui os CPFs são gravados com zeros à esquerda, então
--    cpf = 79190 acha "00000079190", mas cpf = '79190' não acha nada. Use o valor exato.
SELECT id, nome
FROM clientes
WHERE cpf = 79190;

-- 5. JOIN sem índice nos dois lados (hash join): índice sugerido na coluna de junção.
SELECT pg.id, e.transportadora
FROM pagamentos pg
JOIN entregas e ON e.codigo_pedido = pg.pedido_id
WHERE pg.valor > 400;

-- 6. ORDER BY … LIMIT com filesort: índice sugerido em pedidos (status, valor).
SELECT id, valor, criado_em
FROM pedidos
WHERE status = 'pago'
ORDER BY valor DESC
LIMIT 20;

-- 7. OFFSET grande: modelo de paginação por chave.
SELECT id, valor
FROM pedidos
ORDER BY id
LIMIT 200000, 20;

-- 8. LIKE começando com %: modelo de índice FULLTEXT.
SELECT id, nome
FROM clientes
WHERE nome LIKE '%souza%';
