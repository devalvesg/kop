import logging
import requests
import config

logger = logging.getLogger("WHATSAPP")


def _is_bridge_connected() -> bool:
    try:
        resp = requests.get(f"{config.WHATSAPP_BRIDGE_URL}/status", timeout=5)
        data = resp.json()
        connected = data.get("connected", False)
        logger.info(f"Bridge status: {'connected' if connected else 'disconnected'}")
        return connected
    except Exception as e:
        logger.error(f"Não foi possível conectar ao WhatsApp bridge: {e}")
        return False


def send_message(message: str, image_url: str = "", affiliate_link: str = "", group_ids: list[str] | None = None):
    target_ids = group_ids or config.WHATSAPP_GROUP_IDS
    if not target_ids:
        logger.warning("Nenhum group ID configurado, pulando envio")
        raise RuntimeError("Nenhum group ID configurado")

    if not _is_bridge_connected():
        logger.warning("WhatsApp bridge desconectado, pulando envio")
        raise RuntimeError("WhatsApp bridge desconectado")

    full_message = f"{message}\n\n🔗 {affiliate_link}" if affiliate_link else message

    logger.info(f"Enviando para {len(target_ids)} grupos...")

    errors = []
    for group_id in target_ids:
        try:
            payload = {
                "chatId": group_id,
                "message": full_message,
            }
            if image_url:
                payload["imageUrl"] = image_url

            resp = requests.post(
                f"{config.WHATSAPP_BRIDGE_URL}/send",
                json=payload,
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info(f"Enviado com sucesso para {group_id}")
            else:
                error_msg = f"HTTP {resp.status_code} - {resp.text}"
                logger.error(f"ERRO ao enviar para {group_id}: {error_msg}")
                errors.append(error_msg)
        except Exception as e:
            logger.error(f"ERRO ao enviar para {group_id}: {e}")
            errors.append(str(e))

    if len(errors) == len(target_ids):
        raise RuntimeError(f"Falha em todos os grupos WhatsApp: {'; '.join(errors)}")
