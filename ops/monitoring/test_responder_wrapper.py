import os
import sys
import unittest

sys.path.insert(0, '/app')
os.environ['BOT_TOKEN'] = '123456:offline-test-token'
import run_responder


class ResponderWrapperTests(unittest.TestCase):
    def test_existing_handlers_and_monitored_polling(self):
        app = run_responder.build_application()
        handlers = app.handlers[0]
        self.assertEqual(len(handlers), 2)
        self.assertEqual(handlers[0].commands, frozenset({'chatid'}))
        self.assertIs(handlers[0].callback, run_responder.responder.chatid)
        self.assertIs(handlers[1].callback, run_responder.responder.gestisci)
        self.assertIsInstance(app.bot.request, run_responder.responder.Application.builder().token('123456:offline-test-token').build().bot.request.__class__)
        self.assertIsInstance(app.bot._request[0], run_responder.HealthRequest)
        self.assertEqual(app.post_init.__self__.service, 'risponditore')
        self.assertIs(app.post_init.__self__, app.post_shutdown.__self__)


if __name__ == '__main__':
    unittest.main()
