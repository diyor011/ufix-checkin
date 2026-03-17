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
        # Disable signal handlers for aiogram in non-main thread
        import aiogram.dispatcher.dispatcher as dp_module
        original = dp_module.Dispatcher.start_polling
        async def patched_polling(self, *bots, **kwargs):
            kwargs['handle_signals'] = False
            return await original(self, *bots, **kwargs)
        dp_module.Dispatcher.start_polling = patched_polling
        loop.run_until_complete(bot_module.main())

    threading.Thread(target=run_bots, daemon=True).start()
    print("[BOTS] Started in background thread")
