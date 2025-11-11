#!/usr/bin/env bash
set -euo pipefail

echo "[init] Provisionando recursos no LocalStack..."

export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1}

# DynamoDB
echo "[init] Criando tabela DynamoDB: Pedidos"
awslocal dynamodb create-table \
  --table-name Pedidos \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST >/dev/null 2>&1 || echo "[init] Tabela já existe"

# S3
echo "[init] Criando bucket S3: comprovantes"
awslocal s3api create-bucket --bucket comprovantes >/dev/null 2>&1 || echo "[init] Bucket já existe"

# SQS
echo "[init] Criando fila SQS: pedidos-queue"
QUEUE_URL=$(awslocal sqs create-queue --queue-name pedidos-queue --query 'QueueUrl' --output text)
QUEUE_ARN=$(awslocal sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
echo "[init] Fila criada: $QUEUE_URL ($QUEUE_ARN)"

# Zipa lambdas usando Python (sem dependência do utilitário zip)
echo "[init] Empacotando lambdas"
python - <<'PYZIP'
import zipfile

def make_zip(src_py, zip_path):
    z = zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED)
    z.write(src_py, arcname='main.py')
    z.close()

make_zip('/opt/localstack/lambdas/create_order/main.py', '/tmp/create_order.zip')
make_zip('/opt/localstack/lambdas/process_order/main.py', '/tmp/process_order.zip')
print('Zips criados em /tmp')
PYZIP

# Lambda: create-order
echo "[init] Criando Lambda: create-order"
awslocal lambda create-function \
  --function-name create-order \
  --runtime python3.11 \
  --role arn:aws:iam::000000000000:role/lambda-role \
  --handler main.handler \
  --zip-file fileb:///tmp/create_order.zip \
  --environment Variables={AWS_ENDPOINT_URL=http://localstack:4566,DYNAMO_TABLE=Pedidos,SQS_QUEUE_URL=$QUEUE_URL,S3_BUCKET=comprovantes} >/dev/null 2>&1 || echo "[init] Lambda create-order já existe"

# Lambda: process-order
echo "[init] Criando Lambda: process-order"
awslocal lambda create-function \
  --function-name process-order \
  --runtime python3.11 \
  --role arn:aws:iam::000000000000:role/lambda-role \
  --handler main.handler \
  --zip-file fileb:///tmp/process_order.zip \
  --environment Variables={AWS_ENDPOINT_URL=http://localstack:4566,DYNAMO_TABLE=Pedidos,S3_BUCKET=comprovantes} >/dev/null 2>&1 || echo "[init] Lambda process-order já existe"

# Event Source Mapping: SQS -> process-order
echo "[init] Criando event source mapping SQS -> process-order"
awslocal lambda create-event-source-mapping \
  --event-source-arn "$QUEUE_ARN" \
  --function-name process-order \
  --batch-size 1 >/dev/null 2>&1 || echo "[init] Mapping já existe"

# API Gateway REST
echo "[init] Configurando API Gateway"
API_ID=$(awslocal apigateway create-rest-api --name RestauranteAPI --query 'id' --output text)
PARENT_ID=$(awslocal apigateway get-resources --rest-api-id "$API_ID" --query 'items[?path==`/`].id' --output text)
RESOURCE_ID=$(awslocal apigateway create-resource --rest-api-id "$API_ID" --parent-id "$PARENT_ID" --path-part pedidos --query 'id' --output text)

awslocal apigateway put-method \
  --rest-api-id "$API_ID" \
  --resource-id "$RESOURCE_ID" \
  --http-method POST \
  --authorization-type "NONE" >/dev/null

LAMBDA_URI="arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:000000000000:function:create-order/invocations"
awslocal apigateway put-integration \
  --rest-api-id "$API_ID" \
  --resource-id "$RESOURCE_ID" \
  --http-method POST \
  --type AWS_PROXY \
  --integration-http-method POST \
  --uri "$LAMBDA_URI" >/dev/null

# Permitir invocação da Lambda pelo API Gateway
awslocal lambda add-permission \
  --function-name create-order \
  --statement-id apigw-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn arn:aws:execute-api:us-east-1:000000000000:$API_ID/*/POST/pedidos >/dev/null 2>&1 || true

awslocal apigateway create-deployment --rest-api-id "$API_ID" --stage-name dev >/dev/null

API_URL="http://localhost:4566/restapis/${API_ID}/dev/_user_request_/pedidos"
echo "[init] API pronta: POST ${API_URL}"
echo "[init] Provisionamento concluído."