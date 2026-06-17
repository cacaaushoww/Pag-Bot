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
import re
import base64
import unicodedata

try:
    import qrcode
except ImportError:
    qrcode = None

# Dados fixos do recebedor
NOME_RECEBEDOR_PADRAO = "VENDABOT"
CIDADE_RECEBEDOR_PADRAO = "SAO PAULO"


# ──────────────────────────────────────────────
#  DETECÇÃO E NORMALIZAÇÃO DE CHAVE PIX
# ──────────────────────────────────────────────

def _somente_digitos(texto):
    return re.sub(r'\D', '', texto)


def detectar_tipo_chave(chave):
    """
    Detecta o tipo da chave PIX informada.
    Retorna uma string: 'cpf', 'cnpj', 'telefone', 'email' ou 'aleatoria'.
    """
    chave = chave.strip()
    digitos = _somente_digitos(chave)

    # CPF: 11 dígitos (pode vir como 000.000.000-00 ou 00000000000)
    if re.fullmatch(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', chave) or (digitos.isdigit() and len(digitos) == 11 and not chave.startswith('+')):
        return 'cpf'

    # CNPJ: 14 dígitos
    if re.fullmatch(r'\d{2}\.?\d{3}\.?\d{3}/?0001-?\d{2}', chave) or (digitos.isdigit() and len(digitos) == 14):
        return 'cnpj'

    # Telefone: começa com + ou tem 10-11 dígitos com código de área
    if re.fullmatch(r'\+?55\s?\(?\d{2}\)?\s?\d{4,5}-?\d{4}', chave) or re.fullmatch(r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}', chave):
        return 'telefone'

    # E-mail
    if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', chave):
        return 'email'

    # Chave aleatória (UUID): 32 hex com hífens
    if re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', chave):
        return 'aleatoria'

    # Se tiver só dígitos com 11 caracteres, assume CPF; com 14, CNPJ
    if digitos and len(digitos) == 11:
        return 'cpf'
    if digitos and len(digitos) == 14:
        return 'cnpj'

    return 'aleatoria'


def normalizar_chave(chave):
    """
    Normaliza a chave PIX para o formato exigido pelo Banco Central:
      - CPF:      somente dígitos (11)        ex: 12345678900
      - CNPJ:     somente dígitos (14)        ex: 12345678000195
      - Telefone: +55DDDNUMERO (sem espaços)  ex: +5511999999999
      - E-mail:   minúsculas, sem espaços     ex: user@exemplo.com
      - Aleatória: sem alteração              ex: xxxxxxxx-xxxx-...
    """
    chave = chave.strip()
    tipo = detectar_tipo_chave(chave)

    if tipo == 'cpf':
        return _somente_digitos(chave)  # remove pontos e traço

    if tipo == 'cnpj':
        return _somente_digitos(chave)  # remove pontos, barra e traço

    if tipo == 'telefone':
        digitos = _somente_digitos(chave)
        # Garante prefixo +55
        if not digitos.startswith('55') or len(digitos) < 12:
            digitos = '55' + digitos.lstrip('0')
        return '+' + digitos

    if tipo == 'email':
        return chave.lower()

    # Aleatória: mantém como está (UUID é case-insensitive, mas lowercase é padrão)
    return chave.lower()


def formatar_chave_exibicao(chave):
    """
    Formata a chave para exibição amigável ao usuário.
      - CPF:      000.000.000-00
      - CNPJ:     00.000.000/0001-00
      - Telefone: +55 (11) 99999-9999
      - E-mail:   como está (lowercase)
      - Aleatória: como está
    """
    tipo = detectar_tipo_chave(chave)
    digitos = _somente_digitos(chave)

    if tipo == 'cpf' and len(digitos) == 11:
        return f'{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}'

    if tipo == 'cnpj' and len(digitos) == 14:
        return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}'

    if tipo == 'telefone':
        d = digitos.lstrip('55') if digitos.startswith('55') else digitos
        if len(d) == 11:
            return f'+55 ({d[:2]}) {d[2:7]}-{d[7:]}'
        if len(d) == 10:
            return f'+55 ({d[:2]}) {d[2:6]}-{d[6:]}'
        return '+' + digitos

    if tipo == 'email':
        return chave.lower()

    return chave  # aleatória: sem mudança


LABEL_TIPO = {
    'cpf':       'CPF',
    'cnpj':      'CNPJ',
    'telefone':  'Telefone',
    'email':     'E-mail',
    'aleatoria': 'Chave Aleatória',
}


# ──────────────────────────────────────────────
#  HELPERS INTERNOS DO EMV / BR CODE
# ──────────────────────────────────────────────

def _remover_acentos(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _sanitizar(texto, tamanho_max):
    texto = _remover_acentos(texto or "").upper()
    texto = "".join(c for c in texto if c.isalnum() or c in " .,-")
    return texto.strip()[:tamanho_max]


def _emv_campo(id_campo, valor):
    tamanho = f"{len(valor):02d}"
    return f"{id_campo}{tamanho}{valor}"


def _crc16_ccitt(payload):
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


# ──────────────────────────────────────────────
#  FUNÇÃO PRINCIPAL
# ──────────────────────────────────────────────

def gerar_payload_pix(chave_pix, valor, descricao="", nome_recebedor=None, cidade_recebedor=None, txid="***"):
    """
    Monta o BR Code (payload EMV) completo para um pagamento PIX com valor fixo.
    A chave é detectada e normalizada automaticamente.
    Retorna (payload_str, tipo_chave, chave_formatada).
    """
    if not chave_pix:
        raise ValueError("Chave PIX não configurada")

    tipo = detectar_tipo_chave(chave_pix)
    chave_normalizada = normalizar_chave(chave_pix)

    nome = _sanitizar(nome_recebedor or NOME_RECEBEDOR_PADRAO, 25) or "VENDABOT"
    cidade = _sanitizar(cidade_recebedor or CIDADE_RECEBEDOR_PADRAO, 15) or "SAO PAULO"
    descricao_limpa = _sanitizar(descricao, 40)

    gui = _emv_campo("00", "BR.GOV.BCB.PIX")
    chave = _emv_campo("01", chave_normalizada)
    info_adicional_mai = _emv_campo("02", descricao_limpa) if descricao_limpa else ""
    merchant_account_info = _emv_campo("26", gui + chave + info_adicional_mai)

    txid_campo = _emv_campo("05", txid if txid else "***")
    additional_data_field = _emv_campo("62", txid_campo)

    valor_formatado = f"{float(valor):.2f}"

    campos = [
        _emv_campo("00", "01"),
        _emv_campo("01", "12"),
        merchant_account_info,
        _emv_campo("52", "0000"),
        _emv_campo("53", "986"),
        _emv_campo("54", valor_formatado),
        _emv_campo("58", "BR"),
        _emv_campo("59", nome),
        _emv_campo("60", cidade),
        additional_data_field,
    ]

    payload_sem_crc = "".join(campos) + "6304"
    crc = _crc16_ccitt(payload_sem_crc)
    payload = payload_sem_crc + crc

    return payload, tipo, formatar_chave_exibicao(chave_pix)


def gerar_qrcode_base64(payload_pix):
    if qrcode is None:
        return None
    img = qrcode.make(payload_pix, error_correction=qrcode.constants.ERROR_CORRECT_M)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


# ──────────────────────────────────────────────
#  TESTE RÁPIDO
# ──────────────────────────────────────────────

if __name__ == "__main__":
    testes = [
        ("123.456.789-00",         10.50, "CPF com máscara"),
        ("12345678900",            10.50, "CPF sem máscara"),
        ("12.345.678/0001-95",     50.00, "CNPJ com máscara"),
        ("12345678000195",         50.00, "CNPJ sem máscara"),
        ("+5511999999999",         20.00, "Telefone com +55"),
        ("11999999999",            20.00, "Telefone sem +55"),
        ("teste@vendabot.com",     30.00, "E-mail"),
        ("a1b2c3d4-e5f6-7890-abcd-ef1234567890", 99.90, "Chave aleatória"),
    ]

    for chave, valor, descricao in testes:
        tipo = detectar_tipo_chave(chave)
        normalizada = normalizar_chave(chave)
        exibicao = formatar_chave_exibicao(chave)
        payload, _, _ = gerar_payload_pix(chave, valor, descricao)
        print(f"\n[{LABEL_TIPO[tipo]}] entrada: {chave!r}")
        print(f"  normalizada : {normalizada}")
        print(f"  exibição    : {exibicao}")
        print(f"  payload ok  : {'SIM' if len(payload) > 50 else 'ERRO'}")
