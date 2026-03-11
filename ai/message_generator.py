import logging
import re
from collections import Counter
from groq import Groq
import config
from models.product import Product

logger = logging.getLogger("AI")

SYSTEM_PROMPT = """Você cria mensagens promocionais curtas para WhatsApp no Brasil.

FORMATAÇÃO WHATSAPP (OBRIGATÓRIA):
- *texto* = negrito (UM asterisco de cada lado, nunca dois)
- ~texto~ = riscado
- Use DUAS quebra de linha entre seções

ESTRUTURA EXATA (não adicione nada além disso):
[1 emoji] [FRASE DE ABERTURA]

*[Título do produto]*

De ~R$ XXX~ (SÓ se preço original foi informado e diferente do atual)
Por *R$ XXX* à vista

REGRAS CRÍTICAS:
- NUNCA use ** (dois asteriscos). WhatsApp usa *texto* (um asterisco)
- NUNCA inclua link, emoji de link, ou 🔗 (será adicionado automaticamente)
- NUNCA inclua linha de cupom (será adicionada automaticamente após sua mensagem)
- NUNCA inclua explicações, comentários ou notas sobre a mensagem
- NUNCA repita a mesma frase de abertura. Cada mensagem DEVE ter uma frase diferente
- Se o título tiver mais de 60 caracteres, RESUMA mantendo o essencial
- Se preço original NÃO foi informado, NÃO inclua a linha "De ~R$ XXX~"
- Se tiver info de vendas, mencione brevemente
- Use apenas 1 emoji (na abertura)
- Linguagem informal brasileira
- Gere SOMENTE a mensagem, nada mais

FRASES DE ABERTURA (varie e associe de acordo com o produto):
- Eletrônicos: "HORA DE TROCAR O SEU", "TECNOLOGIA COM DESCONTO"
- Casa/cozinha: "SUA CASA MERECE", "UPGRADE NA COZINHA"
- Ferramentas: "FAZ TU MESMO E ECONOMIZA", "CAIXA DE FERRAMENTAS APROVADA"
- Genérico: "ACHEI ESSE PRECINHO", "OLHA ESSE PREÇO", "QUE OFERTAÇO", "BARATO ASSIM É RARO"
- Humor: "NOBODY BATE ESSE PREÇO", "TÁ MAIS BARATO QUE ÁGUA", "PREÇO DE BANANA"
- Urgência: "VAI ACABAR", "CORRE QUE TÁ VOANDO"

Seja criativo e busque frases diferentes para cada tipo de produto, não se prenda as que mandei, apenas use de exemplo

EXEMPLO COM DESCONTO:
🔥 SUA CASA MERECE

*Lixeira Inteligente com Sensor 16L*

De ~R$ 120,00~
Por *R$ 55,92* à vista

EXEMPLO SEM DESCONTO:
💰 ACHEI ESSE PRECINHO

*Fone Bluetooth TWS com Cancelamento de Ruído*

Por *R$ 45,90* à vista"""


def _parse_price(price_str: str) -> float:
    """Converte string de preço para float. Ex: 'R$ 1.234,56' -> 1234.56"""
    if not price_str:
        return 0.0
    cleaned = re.sub(r'[^\d,.]', '', price_str)
    # Formato BR: 1.234,56 -> remover pontos de milhar, trocar vírgula por ponto
    if ',' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _has_valid_discount(product: Product) -> bool:
    """Verifica se o desconto é real (preço original > preço atual)."""
    if not product.original_price:
        return False
    original = _parse_price(product.original_price)
    current = _parse_price(product.price)
    return original > current > 0


def _sanitize_message(message: str) -> str:
    """Remove texto extra que a IA possa gerar além da estrutura definida."""
    lines = message.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        # Parar se encontrar explicações/comentários da IA
        if stripped.startswith("(") and stripped.endswith(")"):
            break
        if any(stripped.lower().startswith(p) for p in [
            "parece que", "nota:", "obs:", "note:", "observação:",
            "vamos seguir", "houve um erro", "esse texto",
        ]):
            break
        clean_lines.append(line)
    # Remover linhas vazias do final
    while clean_lines and not clean_lines[-1].strip():
        clean_lines.pop()
    return "\n".join(clean_lines)


def _is_garbled(message: str) -> bool:
    """Detecta output com repetição colapsada (ex: 'Page Page Page...')."""
    words = re.findall(r'\b\w+\b', message)
    if len(words) < 5:
        return False
    ignore = {"r$", "de", "a", "o", "e", "por", "na", "no", "com", "à", "as", "os", "um", "uma"}
    counts = Counter(w.lower() for w in words)
    for word, count in counts.most_common(5):
        if word not in ignore and count > 4:
            logger.warning(f"Output suspeito: palavra '{word}' aparece {count}x")
            return True
    return False


def _format_sales_info(product: Product) -> str:
    """Retorna info de vendas formatada apenas se relevante (>1000 vendas e rating >= 4.9)."""
    if not product.sales_info or not product.rating:
        return "N/A"
    # Extrair número de vendas
    sales_match = re.search(r'(\d[\d.]*)', product.sales_info.replace('.', ''))
    rating_match = re.search(r'(\d+[.,]?\d*)', product.rating)
    if not sales_match or not rating_match:
        return "N/A"
    try:
        sales_num = int(sales_match.group(1))
        rating_num = float(rating_match.group(1).replace(',', '.'))
    except ValueError:
        return "N/A"
    if sales_num >= 1000 and rating_num >= 4.9:
        return f"{product.sales_info} com {product.rating} estrelas (INCLUIR em itálico usando _texto_)"
    return "N/A"


def generate_message(product: Product, used_titles: list[str] | None = None) -> str:
    logger.info(f"Gerando mensagem para produto {product.mlb_id}...")

    client = Groq(api_key=config.GROQ_API_KEY)

    # Validar desconto real
    original_price_info = "Não informado"
    if _has_valid_discount(product):
        original_price_info = product.original_price

    sales_info = _format_sales_info(product)

    user_content = f"""Crie uma mensagem promocional para este produto:
- Nome: {product.title}
- Preço atual: {product.price}
- Preço original (de): {original_price_info}
- Avaliação: {sales_info}
- Vendas: {sales_info}"""

    if used_titles:
        titles_list = "\n".join(f"- {t}" for t in used_titles)
        user_content += f"\n\nFrases de abertura já utilizadas hoje (NÃO repita nenhuma delas, crie algo DIFERENTE):\n{titles_list}"

    max_retries = 3
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=300,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
            message = response.choices[0].message.content.strip()
            if _is_garbled(message):
                logger.warning(f"Output inválido na tentativa {attempt}/{max_retries}, retentando...")
                last_error = Exception("Output com repetição colapsada")
                continue
            message = _sanitize_message(message)
            logger.info(f"Mensagem gerada ({len(message)} caracteres)")
            return message
        except Exception as e:
            logger.error(f"ERRO na geração para {product.mlb_id} ({product.title[:50]}) tentativa {attempt}/{max_retries}: {e}")
            last_error = e

    raise last_error or Exception("Falha ao gerar mensagem após todas as tentativas")


def extract_title(message: str) -> str:
    """Extrai a frase de abertura da mensagem gerada (primeira linha, sem emoji)."""
    first_line = message.split("\n")[0].strip()
    title = re.sub(r'^[\U0001F000-\U0001FFFF\u2600-\u27FF\u200d\ufe0f]+\s*', '', first_line).strip()
    return title
