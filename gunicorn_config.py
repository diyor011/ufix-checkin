import threading
import asyncio
import os
import sys

def on_starting(server):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    def run_bots():
        import bot as bot_module
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_module.main())

    threading.Thread(target=run_bots, daemon=True).start()
    print("[BOTS] Started in background thread")
