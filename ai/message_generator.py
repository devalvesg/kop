import logging
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


def generate_message(product: Product, used_titles: list[str] | None = None) -> str:
    logger.info(f"Gerando mensagem para produto {product.mlb_id}...")

    client = Groq(api_key=config.GROQ_API_KEY)

    user_content = f"""Crie uma mensagem promocional para este produto:
- Nome: {product.title}
- Preço atual: {product.price}
- Preço original (de): {product.original_price or 'Não informado'}
- Avaliação: {product.rating or 'N/A'}
- Vendas: {product.sales_info or 'N/A'}"""

    if used_titles:
        titles_list = "\n".join(f"- {t}" for t in used_titles)
        user_content += f"\n\nFrases de abertura já utilizadas hoje (NÃO repita nenhuma delas, crie algo DIFERENTE):\n{titles_list}"

    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-4-maverick-17b-128e-instruct",
            max_tokens=300,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        message = response.choices[0].message.content.strip()
        logger.info(f"Mensagem gerada ({len(message)} caracteres)")
        return message
    except Exception as e:
        logger.error(f"ERRO na geração para {product.mlb_id} ({product.title[:50]}): {e}")
        raise


def extract_title(message: str) -> str:
    """Extrai a frase de abertura da mensagem gerada (primeira linha, sem emoji)."""
    first_line = message.split("\n")[0].strip()
    # Remover emoji do início (1-2 primeiros caracteres podem ser emoji + espaço)
    import re
    title = re.sub(r'^[\U0001F000-\U0001FFFF\u2600-\u27FF\u200d\ufe0f]+\s*', '', first_line).strip()
    return title
