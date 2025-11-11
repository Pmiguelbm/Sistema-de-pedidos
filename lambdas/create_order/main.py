import json
import os
import uuid
from typing import Any, Dict

import boto3


REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
TABLE_NAME = os.getenv("DYNAMO_TABLE", "Pedidos")
QUEUE_URL = os.getenv("SQS_QUEUE_URL")


dynamodb = boto3.resource("dynamodb", region_name=REGION, endpoint_url=ENDPOINT_URL)
sqs = boto3.client("sqs", region_name=REGION, endpoint_url=ENDPOINT_URL)


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    # Debug para entender formato recebido via API Gateway/LocalStack
    try:
        print(f"[create-order] body_type={type(body).__name__} isB64={event.get('isBase64Encoded')} raw={str(body)[:300]}")
    except Exception:
        pass
    if body is None:
        raise ValueError("Body inválido ou ausente")

    # Em integrações AWS_PROXY, body pode vir base64
    if isinstance(body, str):
        import base64
        # Primeiro tenta JSON direto
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # Fallback: tenta decodificar como base64 e então interpretar JSON
            try:
                decoded = base64.b64decode(body)
                return json.loads(decoded.decode("utf-8"))
            except Exception:
                # Fallback adicional: normaliza escapes estranhos (ex.: \:, \,, \[) e tenta
                # parse de formato "cliente:Joao,itens:[Pizza,Refri],mesa:5"
                import re
                try:
                    cleaned = body.replace("\\", "")
                    cleaned = cleaned.strip()
                    # Remove chaves externas e aspas supérfluas
                    if cleaned.startswith('{') and cleaned.endswith('}'):
                        cleaned = cleaned[1:-1]
                    cleaned = cleaned.replace('"', '').replace("'", "")
                    cliente_m = re.search(r"cliente\s*:\s*([^,}]+)", cleaned)
                    mesa_m = re.search(r"mesa\s*:\s*([0-9]+)", cleaned)
                    itens_m = re.search(r"itens\s*:\s*\[([^\]]*)\]", cleaned)
                    if not (cliente_m and mesa_m and itens_m):
                        raise ValueError("match inválido")
                    cliente = cliente_m.group(1).strip()
                    mesa = int(mesa_m.group(1))
                    itens = [i.strip() for i in itens_m.group(1).split(',') if i.strip()]
                    return {"cliente": cliente, "mesa": mesa, "itens": itens}
                except Exception:
                    raise ValueError("Body inválido: JSON/base64 malformado")
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            raise ValueError("Body inválido: JSON malformado")
    if isinstance(body, dict):
        return body
    raise ValueError("Body inválido ou ausente")


def _validate(payload: Dict[str, Any]) -> None:
    if "cliente" not in payload or not isinstance(payload["cliente"], str) or not payload["cliente"].strip():
        raise ValueError("Campo 'cliente' é obrigatório e deve ser string")

    if "itens" not in payload or not isinstance(payload["itens"], list) or not payload["itens"]:
        raise ValueError("Campo 'itens' é obrigatório e deve ser uma lista")

    if "mesa" not in payload or not isinstance(payload["mesa"], int) or payload["mesa"] <= 0:
        raise ValueError("Campo 'mesa' é obrigatório e deve ser inteiro positivo")


def handler(event, context):
    try:
        payload = _parse_body(event)
        _validate(payload)

        order_id = str(uuid.uuid4())
        item = {
            "id": order_id,
            "cliente": payload["cliente"],
            "itens": payload["itens"],
            "mesa": payload["mesa"],
            "status": "RECEBIDO",
        }

        # Salva no DynamoDB
        table = dynamodb.Table(TABLE_NAME)
        table.put_item(Item=item)

        # Envia ID para SQS
        if not QUEUE_URL:
            raise RuntimeError("SQS_QUEUE_URL não configurada no ambiente")
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"id": order_id}))

        return {
            "statusCode": 201,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"id": order_id, "status": item["status"]}),
        }

    except ValueError as ve:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"erro": str(ve)}),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"erro": "Falha interna", "detalhes": str(e)}),
        }