-- Banco de demonstração do plano de execução (Visual Explain) do my-gui.
-- Os dados são gerados aqui mesmo, de forma determinística, para disparar cada diagnóstico e
-- cada sugestão: veja consultas.sql. Uns 20 a 40 segundos para carregar.
SET SESSION cte_max_recursion_depth = 1000000;

-- 20 mil clientes; 95% são de SP (dado desbalanceado de propósito: o MySQL chuta 10% para
-- "uf = 'SP'" porque a coluna não tem índice nem histograma).
CREATE TABLE clientes (
  id INT PRIMARY KEY,
  nome VARCHAR(100) NOT NULL,
  cpf VARCHAR(14) NOT NULL,
  uf CHAR(2) NOT NULL,
  limite DECIMAL(10,2) NOT NULL,
  criado_em DATETIME NOT NULL,
  UNIQUE KEY uk_clientes_cpf (cpf)
);
INSERT INTO clientes
WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s WHERE n < 20000)
SELECT n,
  CONCAT(ELT(1 + n % 8, 'Ana', 'Bruno', 'Carla', 'Diego', 'Elisa', 'Fábio', 'Gabi', 'Hugo'), ' ',
         ELT(1 + (n DIV 8) % 6, 'Silva', 'Souza', 'Lima', 'Costa', 'Rocha', 'Alves')),
  LPAD(n * 7919, 11, '0'),
  IF(n % 20 = 0, ELT(1 + (n DIV 20) % 5, 'RJ', 'MG', 'PR', 'BA', 'AC'), 'SP'),
  500 + (n * 37) % 4500,
  '2024-01-01' + INTERVAL n * 23 MINUTE
FROM s;

-- 500 mil pedidos ao longo de 2024; só 0,05% estão "estornado" (o MySQL chuta 10% de novo).
CREATE TABLE pedidos (
  id INT PRIMARY KEY,
  cliente_id INT NOT NULL,
  status VARCHAR(20) NOT NULL,
  valor DECIMAL(10,2) NOT NULL,
  criado_em DATETIME NOT NULL,
  KEY ix_pedidos_cliente (cliente_id),
  KEY ix_pedidos_criado (criado_em)
);
INSERT INTO pedidos
WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s WHERE n < 500000)
SELECT n, 1 + (n * 7) % 20000,
  IF(n % 2000 = 0, 'estornado', IF(n % 3 = 0, 'pendente', 'pago')),
  10 + (n * 13) % 990,
  '2024-01-01' + INTERVAL n * 61 SECOND
FROM s;

-- Pagamentos SEM índice em pedido_id (para a subquery correlacionada e o índice na junção).
CREATE TABLE pagamentos (
  id INT PRIMARY KEY,
  pedido_id INT NOT NULL,
  valor DECIMAL(10,2) NOT NULL
);
INSERT INTO pagamentos
WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s WHERE n < 100000)
SELECT n, 1 + n % 50000, 5 + (n * 11) % 500 FROM s;

-- Entregas SEM índice em codigo_pedido (JOIN vira hash join / join buffer).
CREATE TABLE entregas (
  id INT PRIMARY KEY,
  codigo_pedido INT NOT NULL,
  transportadora VARCHAR(40) NOT NULL
);
INSERT INTO entregas
WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s WHERE n < 50000)
SELECT n, n * 3, ELT(1 + n % 4, 'Correios', 'Jadlog', 'Loggi', 'Total Express') FROM s;

ANALYZE TABLE clientes, pedidos, pagamentos, entregas;
