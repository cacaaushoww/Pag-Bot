import json
import requests

class PaymentProcessor:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = "https://api.mercadopago.com"

    def create_pix_payment(self, amount, description, external_reference, payer_email):
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "transaction_amount": amount,
            "description": description,
            "payment_method_id": "pix",
            "external_reference": external_reference,
            "payer": {
                "email": payer_email
            }
        }
        try:
            response = requests.post(f"{self.base_url}/v1/payments", headers=headers, data=json.dumps(payload))
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Erro ao criar pagamento Pix: {e}")
            return None

    def get_payment_status(self, payment_id):
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        try:
            response = requests.get(f"{self.base_url}/v1/payments/{payment_id}", headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Erro ao obter status do pagamento: {e}")
            return None

# Exemplo de uso (será integrado ao bot Discord)
if __name__ == "__main__":
    # Substitua pelo seu Access Token do Mercado Pago
    MP_ACCESS_TOKEN = "SEU_TOKEN_AQUI"
    
    processor = PaymentProcessor(MP_ACCESS_TOKEN)

    # Exemplo de criação de pagamento Pix
    # payment_data = processor.create_pix_payment(10.00, "Produto Teste", "ORDER-123", "test_payer@example.com")
    # if payment_data:
    #     print("Pagamento Pix criado com sucesso:")
    #     print(json.dumps(payment_data, indent=2))
    #     # Aqui você obteria o QR code ou o código Pix para o usuário
    # else:
    #     print("Falha ao criar pagamento Pix.")

    # Exemplo de verificação de status de pagamento
    # payment_id = "SEU_ID_DE_PAGAMENTO"
    # status_data = processor.get_payment_status(payment_id)
    # if status_data:
    #     print("Status do pagamento:")
    #     print(json.dumps(status_data, indent=2))
    # else:
    #     print("Falha ao obter status do pagamento.")
