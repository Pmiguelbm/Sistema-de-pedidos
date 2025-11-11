import json
import os
from typing import Any, Dict

import boto3


REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
TABLE_NAME = os.getenv("DYNAMO_TABLE", "Pedidos")
BUCKET_NAME = os.getenv("S3_BUCKET", "comprovantes")


dynamodb = boto3.resource("dynamodb", region_name=REGION, endpoint_url=ENDPOINT_URL)
s3 = boto3.client("s3", region_name=REGION, endpoint_url=ENDPOINT_URL)


def _fake_pdf_bytes(order: Dict[str, Any]) -> bytes:
    # Conteúdo simples para simular um PDF; suficiente para testes locais
    lines = [
        "Comprovante de Pedido",
        f"ID: {order.get('id')}",
        f"Cliente: {order.get('cliente')}",
        f"Mesa: {order.get('mesa')}",
        f"Itens: {', '.join(order.get('itens', []))}",
        "Status: PROCESSADO",
        "\nObrigado pela preferência!",
    ]
    text = "\n".join(lines)
    header = "%PDF-1.4\n% Comprovante simulado gerado localmente\n".encode("utf-8")
    return header + text.encode("utf-8")


def handler(event, context):
    table = dynamodb.Table(TABLE_NAME)

    for record in event.get("Records", []):
        body = record.get("body")
        try:
            payload = json.loads(body) if isinstance(body, str) else body
            order_id = payload.get("id")
            if not order_id:
                raise ValueError("Mensagem SQS sem 'id' do pedido")

            # Busca o pedido para montar comprovante
            resp = table.get_item(Key={"id": order_id})
            order = resp.get("Item") or {"id": order_id, "cliente": "-", "itens": [], "mesa": "-"}

            # Gera PDF simulado e salva no S3
            key = f"pedido-{order_id}.pdf"
            s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=_fake_pdf_bytes(order), ContentType="application/pdf")

            # Atualiza status
            table.update_item(
                Key={"id": order_id},
                UpdateExpression="SET #s = :processed",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":processed": "PROCESSADO"},
            )

        except Exception as e:
            # Em processamento assíncrono via SQS, registramos erro e seguimos para outras mensagens
            print(f"Falha ao processar registro: {e}")

    # Não há retorno específico para SQS trigger
    return {"status": "ok"}