"""
Main Entry Point — TASK 4.4
Inisialisasi semua clients & agents, jalankan orchestrator.
"""

import asyncio
import logging
import sys

from agents.orchestrator import Orchestrator

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Configure logging ke stdout + file."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("trading_agent.log", encoding="utf-8"),
        ],
    )

    # Reduce noise from third-party libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Entry point utama."""
    setup_logging()
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("AI Trading Agent — Starting")
    logger.info("Stack: Python + MT5 + OpenRouter + MongoDB")
    logger.info("=" * 60)

    orchestrator = Orchestrator()

    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down...")
        await orchestrator.stop()
    except Exception as e:
        logger.critical("Fatal error: %s", e, exc_info=True)
    finally:
        logger.info("AI Trading Agent — Stopped")


if __name__ == "__main__":
    asyncio.run(main())
