const express = require("express");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

const app = express();
app.use(express.json());

const PORT = 3001;

let isReady = false;

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: ".wwebjs_auth" }),
  puppeteer: {
    headless: true,
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
  },
});

client.on("qr", (qr) => {
  console.log("[WHATSAPP] Escaneie o QR code abaixo:");
  qrcode.generate(qr, { small: true });
});

client.on("ready", () => {
  isReady = true;
  console.log("[WHATSAPP] Cliente conectado e pronto!");
});

client.on("disconnected", (reason) => {
  isReady = false;
  console.log(`[WHATSAPP] Desconectado: ${reason}`);
});

client.on("auth_failure", (msg) => {
  console.error(`[WHATSAPP] Falha na autenticação: ${msg}`);
});

app.get("/status", (req, res) => {
  res.json({ connected: isReady });
});

app.get("/groups", async (req, res) => {
  if (!isReady) {
    return res.status(503).json({ error: "WhatsApp não está conectado" });
  }

  try {
    const chats = await client.getChats();
    const groups = chats
      .filter((chat) => chat.isGroup)
      .map((chat) => ({ id: chat.id._serialized, name: chat.name }));

    console.log(`[WHATSAPP] ${groups.length} grupos encontrados`);
    res.json({ groups });
  } catch (error) {
    console.error("[WHATSAPP] Erro ao listar grupos:", error.message);
    res.status(500).json({ error: error.message });
  }
});

app.post("/send", async (req, res) => {
  if (!isReady) {
    return res.status(503).json({ error: "WhatsApp não está conectado" });
  }

  const { chatId, message, imageUrl } = req.body;

  if (!chatId || !message) {
    return res.status(400).json({ error: "chatId e message são obrigatórios" });
  }

  try {
    if (imageUrl) {
      const media = await MessageMedia.fromUrl(imageUrl, {
        unsafeMime: true,
      });
      await client.sendMessage(chatId, media, { caption: message });
    } else {
      await client.sendMessage(chatId, message);
    }

    console.log(`[WHATSAPP] Mensagem enviada para ${chatId}`);
    res.json({ success: true });
  } catch (error) {
    console.error(`[WHATSAPP] Erro ao enviar para ${chatId}:`, error.message);
    res.status(500).json({ error: error.message });
  }
});

client.initialize();

app.listen(PORT, () => {
  console.log(`[WHATSAPP] Bridge rodando na porta ${PORT}`);
});
