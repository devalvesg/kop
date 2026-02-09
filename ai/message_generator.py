import logging
from groq import Groq
import config
from models.product import Product

logger = logging.getLogger("AI")

SYSTEM_PROMPT = """Você cria mensagens promocionais curtas para WhatsApp no Brasil.

FORMATAÇÃO WHATSAPP (OBRIGATÓRIA):
- *texto* = negrito (UM asterisco de cada lado, nunca dois)
- ~texto~ = riscado
- Use DUAS quebras de linha entre seções

ESTRUTURA EXATA (não adicione nada além disso):
[1 emoji] [FRASE DE ABERTURA ÚNICA]

*[Título do produto]*

De ~R$ XXX~ (APENAS se o preço original foi informado e diferente)
Por *R$ XXX* à vista

REGRAS CRÍTICAS:
- NUNCA use ** (dois asteriscos)
- NUNCA inclua link, emoji de link ou 🔗
- NUNCA inclua linha de cupom
- NUNCA inclua explicações, comentários ou notas
- NUNCA reutilize frases de abertura já usadas anteriormente
- É PROIBIDO usar exatamente as frases:
  "QUE OFERTAÇO", "SUA CASA MERECE", "ACHEI ESSE PRECINHO"
- Cada frase de abertura deve ser semanticamente diferente
- Use apenas 1 emoji
- Linguagem informal brasileira
- Gere SOMENTE a mensagem final

CRIATIVIDADE OBRIGATÓRIA:
Antes de gerar a frase de abertura, analise silenciosamente:
- Tipo do produto
- Público-alvo
- Benefício principal
- Sensação gerada (economia, praticidade, status, urgência)

Com base nisso, crie uma FRASE DE ABERTURA ORIGINAL, curta e específica.
Evite frases genéricas ou vagas.

REGRAS DE TÍTULO:
- Máx. 60 caracteres
- Destaque apenas o essencial
- Remova termos redundantes ou técnicos demais

REGRAS DE PREÇO:
- Se não houver preço original, NÃO inclua a linha "De ~R$~"
- Se houver info de vendas, mencione brevemente na frase de abertura
"""


def generate_message(product: Product) -> str:
    logger.info(f"Gerando mensagem para produto {product.mlb_id}...")

    client = Groq(api_key=config.GROQ_API_KEY)

    user_content = f"""Crie uma mensagem promocional para este produto:
- Nome: {product.title}
- Preço atual: {product.price}
- Preço original (de): {product.original_price or 'Não informado'}
- Avaliação: {product.rating or 'N/A'}
- Vendas: {product.sales_info or 'N/A'}"""

    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-4-maverick-17b-128e-instruct",
            max_tokens=300,
            temperature=1.0,
            top_p=0.9,
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
