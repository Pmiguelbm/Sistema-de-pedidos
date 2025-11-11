# Sistema de Pedidos de Restaurante (Serverless) — LocalStack + Docker

Este projeto implementa um fluxo serverless local usando LocalStack:

- API Gateway: endpoint `POST /pedidos` para receber pedidos.
- Lambda `create-order`: valida pedido, salva no DynamoDB e envia ID para SQS.
- DynamoDB: tabela `Pedidos` com chave primária `id`.
- SQS: fila `pedidos-queue` para processamento assíncrono.
- Lambda `process-order`: consome SQS, gera comprovante em PDF (simulado) e salva no S3 (`comprovantes`).

## Pré-requisitos
- Docker Desktop instalado.

## Subir o ambiente
1. Suba o LocalStack:
   ```powershell
   docker compose up -d
   ```
2. Aguarde o bootstrap (o container executa o script `localstack/init/ready.d/01-bootstrap.sh`).
3. Pegue a URL da API nos logs:
   ```powershell
   docker logs localstack | Select-String "API pronta"
   ```
   Você verá algo como:
   ```
   [init] API pronta: POST http://localhost:4566/restapis/xxxxxxxx/dev/_user_request_/pedidos
   ```

## Testar o endpoint
Exemplo de requisição com PowerShell (`Invoke-RestMethod`). Substitua a URL pela dos logs:
```powershell
$url = "http://localhost:4566/restapis/xxxxxxxx/dev/_user_request_/pedidos"
$body = @{ cliente = "João"; itens = @("Pizza","Refri"); mesa = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri $url -Body $body -ContentType "application/json"
```
Resposta esperada:
```json
{
  "id": "<uuid-do-pedido>",
  "status": "RECEBIDO"
}
```

## Verificar persistência e processamento

- DynamoDB (dentro do container LocalStack):
  ```powershell
  docker exec -it localstack awslocal dynamodb scan --table-name Pedidos
  ```

- Objetos no S3 (comprovantes):
  ```powershell
  docker exec -it localstack awslocal s3 ls s3://comprovantes
  # Para copiar um comprovante para sua máquina:
  docker exec -it localstack awslocal s3 cp s3://comprovantes/pedido-<uuid-do-pedido>.pdf /tmp/
  ```

Observação: o PDF é simulado (conteúdo texto com cabeçalho `%PDF-1.4`), suficiente para testes locais.

## Parar e limpar
```powershell
docker compose down
```

## Estrutura do projeto
- `docker-compose.yml`: sobe o LocalStack com serviços necessários.
- `localstack/init/ready.d/01-bootstrap.sh`: cria recursos (API Gateway, DynamoDB, SQS, S3) e registra as Lambdas.
- `lambdas/create_order/main.py`: Lambda para criar pedidos.
- `lambdas/process_order/main.py`: Lambda para processar pedidos e gerar comprovantes.

## Construir manualmente a URL da API
- Caso os logs não mostrem a URL, você pode obter o `API_ID` e montar o endpoint:
  - PowerShell:
    - `docker exec localstack awslocal apigateway get-rest-apis --query 'items[?name==\`PedidosAPI\`].id' --output text`
    - Monte a URL: `http://localhost:4566/restapis/<API_ID>/dev/_user_request_/pedidos`
  - Bash (Linux/macOS):
    - `API_ID=$(docker exec localstack awslocal apigateway get-rest-apis --query 'items[?name==\`PedidosAPI\`].id' --output text)`
    - `echo "http://localhost:4566/restapis/$API_ID/dev/_user_request_/pedidos"`

## Atualizar Lambdas após mudanças no código
- `create-order`:
  - `docker exec localstack bash -lc "cd /opt/localstack/lambdas/create_order && zip -r /tmp/create_order.zip . && awslocal lambda update-function-code --function-name create-order --zip-file fileb:///tmp/create_order.zip"`
- `process-order`:
  - `docker exec localstack bash -lc "cd /opt/localstack/lambdas/process_order && zip -r /tmp/process_order.zip . && awslocal lambda update-function-code --function-name process-order --zip-file fileb:///tmp/process_order.zip"`

## Inspecionar logs
- Seguir logs do LocalStack:
  - `docker logs -f localstack`
- Filtrar logs relacionados às Lambdas (dentro do container):
  - `docker exec localstack bash -lc "awslocal logs tail /aws/lambda/create-order --follow"`
  - `docker exec localstack bash -lc "awslocal logs tail /aws/lambda/process-order --follow"`

## Consultas confiáveis ao DynamoDB (Windows-friendly)
- Evite JSON inline no `--key` usando arquivo:
  - Crie `key.json` com `{"id":{"S":"<uuid-do-pedido>"}}`.
  - `docker exec localstack bash -lc "awslocal dynamodb get-item --table-name Pedidos --key file:///opt/localstack/key.json"`
- Alternativa com Python dentro do container:
  - `docker exec localstack bash -lc "export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test; python - <<'PY'\nimport boto3\nD=boto3.resource('dynamodb',region_name='us-east-1',endpoint_url='http://localhost:4566')\nT=D.Table('Pedidos')\nprint(T.get_item(Key={'id':'<uuid-do-pedido>'}).get('Item'))\nPY"`

## Troubleshooting (Windows/PowerShell)
- `curl.exe` e JSON inline podem quebrar com aspas/escapes. Prefira `Invoke-RestMethod`.
- Para AWS CLI com JSON complexo, use `file://` em vez de inline.
- Se o `boto3` reclamar de credenciais, defina variáveis fake antes do comando:
  - `export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test` (no bash dentro do container)

## Checklist de Entrega
- Ambiente sobe com `docker compose up -d` sem erros.
- `POST /pedidos` responde `201` com `status` `RECEBIDO`.
- DynamoDB contém o pedido e após processamento o `status` vira `PROCESSADO`.
- S3 `comprovantes` possui `pedido-<uuid>.pdf`.
- Logs de `create-order` e `process-order` acessíveis e sem exceptions.