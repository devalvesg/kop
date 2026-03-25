import glob
import logging
import os
import signal
import subprocess
import nodriver as uc
from pyvirtualdisplay import Display
import config

logger = logging.getLogger("BROWSER")

_display: Display | None = None

# Diretório persistente do perfil Chrome (mantém sessões logadas entre restarts)
CHROME_PROFILE_DIR = os.path.join(config._data_dir, "chrome_profile")


def _kill_zombie_chromes():
    """Mata processos Chrome órfãos que podem estar travando o user_data_dir."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"--user-data-dir={CHROME_PROFILE_DIR}"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            if pid.strip():
                try:
                    os.kill(int(pid.strip()), signal.SIGKILL)
                    logger.info(f"Chrome órfão (PID {pid.strip()}) finalizado")
                except (ProcessLookupError, ValueError):
                    pass
    except Exception as e:
        logger.debug(f"Erro ao verificar chromes órfãos: {e}")


def _clean_lock_files():
    """Remove lock files do perfil Chrome que impedem nova instância."""
    lock_patterns = [
        os.path.join(CHROME_PROFILE_DIR, "SingletonLock"),
        os.path.join(CHROME_PROFILE_DIR, "SingletonSocket"),
        os.path.join(CHROME_PROFILE_DIR, "SingletonCookie"),
    ]
    for pattern in lock_patterns:
        for lock_file in glob.glob(pattern):
            try:
                os.remove(lock_file)
                logger.info(f"Lock file removido: {lock_file}")
            except OSError:
                pass


def start_virtual_display():
    """Inicia Xvfb quando HEADLESS=true (nodriver precisa de display real)."""
    global _display
    if config.HEADLESS and _display is None:
        _display = Display(visible=False, size=(1920, 1080))
        _display.start()
        logger.info("PyVirtualDisplay (Xvfb) iniciado")


def stop_virtual_display():
    """Para o Xvfb se estiver rodando."""
    global _display
    if _display:
        _display.stop()
        _display = None
        logger.info("PyVirtualDisplay parado")


async def get_browser() -> uc.Browser:
    """Cria e retorna o browser nodriver com perfil persistente."""
    start_virtual_display()
    logger.info("Iniciando nodriver browser...")

    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)

    # Limpar processos e locks de instâncias anteriores crashadas
    _kill_zombie_chromes()
    _clean_lock_files()

    browser_args = [
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
    ]

    browser = await uc.start(
        headless=False,
        sandbox=False,
        user_data_dir=CHROME_PROFILE_DIR,
        browser_args=browser_args,
        browser_executable_path=config.CHROME_BINARY or None,
    )

    logger.info("nodriver browser criado com sucesso")
    return browser
