"""
Gerador de PIX "puro" (sem Mercado Pago).

Monta o payload EMV (BR Code) usado pelo PIX a partir da chave PIX,
valor, descrição e dados fixos do recebedor. O resultado é o mesmo
tipo de código que apps de banco leem: cola/copia o texto, e o valor
já vem preenchido. Também gera a imagem do QR Code (PNG em base64)
a partir desse mesmo texto, para enviar no Discord.

Não depende de nenhuma API externa — é só matemática/formatação,
de acordo com o padrão definido pelo Banco Central (BR Code / EMVCo).
"""

import io
import base64
import unicodedata

try:
    import qrcode
except ImportError:
    qrcode = None

# Dados fixos do recebedor (combinado com o usuário: valores genéricos por enquanto)
NOME_RECEBEDOR_PADRAO = "VENDABOT"
CIDADE_RECEBEDOR_PADRAO = "SAO PAULO"


def _remover_acentos(texto):
    """O padrão EMV exige apenas caracteres ASCII (sem acentos)."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _sanitizar(texto, tamanho_max):
    """Remove acentos, caracteres especiais problemáticos e corta no tamanho máximo."""
    texto = _remover_acentos(texto or "").upper()
    texto = "".join(c for c in texto if c.isalnum() or c in " .,-")
    return texto.strip()[:tamanho_max]


def _emv_campo(id_campo, valor):
    """Formata um campo EMV: ID (2 dígitos) + Tamanho (2 dígitos) + Valor."""
    tamanho = f"{len(valor):02d}"
    return f"{id_campo}{tamanho}{valor}"


def _crc16_ccitt(payload):
    """
    Calcula o CRC16-CCITT (polinômio 0x1021), exigido pelo padrão EMV/PIX
    como últimos 4 caracteres do código.
    """
    polinomio = 0x1021
    resultado = 0xFFFF

    for byte in payload.encode("utf-8"):
        resultado ^= byte << 8
        for _ in range(8):
            if resultado & 0x8000:
                resultado = ((resultado << 1) ^ polinomio) & 0xFFFF
            else:
                resultado = (resultado << 1) & 0xFFFF

    return f"{resultado:04X}"


def gerar_payload_pix(chave_pix, valor, descricao="", nome_recebedor=None, cidade_recebedor=None, txid="***"):
    """
    Monta o BR Code (payload EMV) completo para um pagamento PIX com valor fixo.

    Args:
        chave_pix: chave PIX cadastrada (CPF, CNPJ, email, telefone ou aleatória)
        valor: valor do pagamento (float)
        descricao: texto curto que aparece como mensagem ao pagador (opcional)
        nome_recebedor: nome exibido para quem paga (padrão: VENDABOT)
        cidade_recebedor: cidade do recebedor (padrão: SAO PAULO)
        txid: identificador da transação (até 25 caracteres, "***" = sem identificador)

    Returns:
        String com o código PIX completo (copia e cola), já com CRC16 válido.
    """
    if not chave_pix:
        raise ValueError("Chave PIX não configurada")

    nome = _sanitizar(nome_recebedor or NOME_RECEBEDOR_PADRAO, 25) or "VENDABOT"
    cidade = _sanitizar(cidade_recebedor or CIDADE_RECEBEDOR_PADRAO, 15) or "SAO PAULO"
    descricao_limpa = _sanitizar(descricao, 40)
    chave_limpa = (chave_pix or "").strip()

    # Merchant Account Information (campo 26) - dados específicos do PIX
    gui = _emv_campo("00", "BR.GOV.BCB.PIX")
    chave = _emv_campo("01", chave_limpa)
    info_adicional_mai = _emv_campo("02", descricao_limpa) if descricao_limpa else ""
    merchant_account_info = _emv_campo("26", gui + chave + info_adicional_mai)

    # Additional Data Field (campo 62) - TxID
    txid_campo = _emv_campo("05", txid if txid else "***")
    additional_data_field = _emv_campo("62", txid_campo)

    valor_formatado = f"{float(valor):.2f}"

    campos = [
        _emv_campo("00", "01"),                          # Payload Format Indicator
        _emv_campo("01", "12"),                           # Point of Initiation Method (12 = estático com valor)
        merchant_account_info,                            # 26 - dados do PIX
        _emv_campo("52", "0000"),                         # Merchant Category Code
        _emv_campo("53", "986"),                           # Moeda (986 = BRL)
        _emv_campo("54", valor_formatado),                 # Valor da transação
        _emv_campo("58", "BR"),                            # País
        _emv_campo("59", nome),                            # Nome do recebedor
        _emv_campo("60", cidade),                          # Cidade do recebedor
        additional_data_field,                             # 62 - TxID
    ]

    payload_sem_crc = "".join(campos) + "6304"
    crc = _crc16_ccitt(payload_sem_crc)

    return payload_sem_crc + crc


def gerar_qrcode_base64(payload_pix):
    """
    Gera a imagem do QR Code a partir do payload PIX, retornando como
    PNG codificado em base64 (pronto para enviar como anexo no Discord).

    Retorna None se a biblioteca 'qrcode' não estiver instalada.
    """
    if qrcode is None:
        return None

    img = qrcode.make(payload_pix, error_correction=qrcode.constants.ERROR_CORRECT_M)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()  # bytes, prontos para discord.File


if __name__ == "__main__":
    # Teste rápido manual
    payload = gerar_payload_pix(
        chave_pix="teste@vendabot.com",
        valor=10.50,
        descricao="Curso Premium"
    )
    print("Payload PIX gerado:")
    print(payload)
    print(f"\nTamanho: {len(payload)} caracteres")
