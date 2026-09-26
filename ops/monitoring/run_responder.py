"""Launch the existing responder handlers with private runtime monitoring."""
import sys
import logging

sys.path.insert(0, '/opt/mulino-libero/app')
import bot_risponditore as responder
from runtime_health import HealthRequest, RuntimeHealth

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


def build_application():
    monitor = RuntimeHealth('risponditore', '/run/mulino-monitor/risponditore.json')
    app = (responder.Application.builder().token(responder.TOKEN)
           .get_updates_request(HealthRequest(monitor))
           .post_init(monitor.start).post_shutdown(monitor.stop).build())
    app.add_handler(responder.CommandHandler('chatid', responder.chatid))
    app.add_handler(responder.MessageHandler(
        responder.filters.TEXT & responder.filters.User(username=responder.BOT_A_USERNAME),
        responder.gestisci))
    return app


if __name__ == '__main__':
    build_application().run_polling(allowed_updates=responder.Update.ALL_TYPES)
