"""Basliksiz calistirma modu: menude 'otomatik' yazmadan dogrudan panel + otomatik modu baslatir.

python service.py ile calistirilir (start_ajans.bat bunu cagirir).
"""
import sys

from dotenv import load_dotenv

import panel
from main import MultiAgentSystem

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()


def main():
    panel_url = panel.start()
    print(f"\n📊 Panel: {panel_url}\n")
    system = MultiAgentSystem()
    system.run_automatic()


if __name__ == "__main__":
    main()
