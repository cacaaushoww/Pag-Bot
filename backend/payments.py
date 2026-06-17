import json
import requests

class PaymentProcessor:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = "https://api.mercadopago.com"

    def create_pix_payment(self, amount, description, external_reference, payer_email):
        """
        Cria um pagamento PIX no Mercado Pago
        Retorna um dict com os dados do pagamento ou erro
        """
        if not self.access_token:
            return {"error": "MP_ACCESS_TOKEN não configurado"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": external_reference  # Evita duplicatas
        }
        
        payload = {
            "transaction_amount": float(amount),
            "description": description,
            "payment_method_id": "pix",
            "external_reference": external_reference,
            "payer": {
                "email": payer_email
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/v1/payments",
                headers=headers,
                json=payload,
                timeout=10
            )
            
            data = response.json()
            
            # Se a resposta for sucesso (200-299)
            if 200 <= response.status_code < 300:
                print(f"✅ Pagamento PIX criado com sucesso!")
                print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
                return data
            
            # Se for erro, retorna a mensagem do Mercado Pago
            else:
                error_msg = data.get("message", f"Erro {response.status_code}")
                print(f"❌ Erro ao criar pagamento: {error_msg}")
                print(f"Response completa: {json.dumps(data, indent=2, ensure_ascii=False)}")
                return {
                    "error": error_msg,
                    "status_code": response.status_code,
                    "details": data
                }
                
        except requests.exceptions.Timeout:
            return {"error": "Timeout na requisição ao Mercado Pago (10s)"}
        except requests.exceptions.ConnectionError:
            return {"error": "Erro de conexão com o Mercado Pago"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Erro na requisição: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "Resposta inválida do Mercado Pago (não é JSON)"}

    def get_payment_status(self, payment_id):
        """Obtém o status de um pagamento"""
        if not self.access_token:
            return {"error": "MP_ACCESS_TOKEN não configurado"}
            
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/v1/payments/{payment_id}",
                headers=headers,
                timeout=10
            )
            
            data = response.json()
            
            if 200 <= response.status_code < 300:
                return data
            else:
                return {
                    "error": data.get("message", f"Erro {response.status_code}"),
                    "status_code": response.status_code
                }
                
        except Exception as e:
            return {"error": f"Erro ao obter status: {str(e)}"}

# Exemplo de uso (será integrado ao bot Discord)
if __name__ == "__main__":
    import os
    
    MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "SEU_TOKEN_AQUI")
    
    processor = PaymentProcessor(MP_ACCESS_TOKEN)

    # Exemplo de criação de pagamento PIX
    payment_data = processor.create_pix_payment(
        amount=10.00,
        description="Produto Teste",
        external_reference="ORDER-123",
        payer_email="test_payer@example.com"
    )
    
    print("\n=== Resposta do Mercado Pago ===")
    print(json.dumps(payment_data, indent=2, ensure_ascii=False))
    
    # Verifica a estrutura da resposta
    if "point_of_interaction" in payment_data:
        qr_code = payment_data["point_of_interaction"]["transaction_data"]["qr_code"]
        print(f"\n✅ QR Code gerado: {qr_code}")
    elif "error" in payment_data:
        print(f"\n❌ Erro: {payment_data['error']}")
