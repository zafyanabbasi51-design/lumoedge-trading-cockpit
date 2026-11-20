"""
=============================================================================
 LUMO EDGE FOREX BOT - 3D APP LAUNCHER
 Owner: Gontse
=============================================================================
"""

import time
import webbrowser
import threading
import uvicorn
import os
import sys

# Ensure current dir in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def open_browser():
    time.sleep(1.8)
    url = "http://127.0.0.1:8000"
    print(f"\n[+] Opening Lumo Edge 3D Cockpit Interface at: {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    print("=" * 65)
    print("       LUMO EDGE 3D FOREX COCKPIT - ARCHITECT: GONTSE        ")
    print("=" * 65)
    print("[*] Starting backend AI engine and 3D web server...")
    
    # Launch browser automatically in background thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run Uvicorn server
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
