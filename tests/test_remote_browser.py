from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from test_regressions import worker


URL = 'https://mulino-browser.tail1ce920.ts.net/vnc.html?autoconnect=1&resize=scale'


class PrivateBrowserCommandTests(unittest.IsolatedAsyncioTestCase):
    def context(self, user_id=99, chat_type='private', url=URL):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_user=SimpleNamespace(id=user_id),
                                 effective_chat=SimpleNamespace(type=chat_type), effective_message=message)
        coordinator = SimpleNamespace(settings=SimpleNamespace(admin_id=99, remote_browser_url=url))
        context = SimpleNamespace(application=SimpleNamespace(bot_data={'coordinator': coordinator}))
        return update, context

    async def test_admin_private_receives_configured_url_without_preview(self):
        update, context = self.context()
        await worker.browser_command(update, context)
        reply = update.effective_message.reply_text
        reply.assert_awaited_once()
        self.assertIn(URL, reply.call_args.args[0])
        self.assertIn('Tailscale', reply.call_args.args[0])
        self.assertTrue(reply.call_args.kwargs['disable_web_page_preview'])

    async def test_other_users_and_groups_receive_nothing(self):
        for user_id, chat_type in ((11, 'private'), (99, 'group'), (99, 'supergroup'), (11, 'supergroup')):
            with self.subTest(user_id=user_id, chat_type=chat_type):
                update, context = self.context(user_id, chat_type)
                await worker.browser_command(update, context)
                update.effective_message.reply_text.assert_not_awaited()

    async def test_absent_user_chat_or_message_receive_nothing(self):
        for field in ('effective_user', 'effective_chat', 'effective_message'):
            update, context = self.context()
            message = update.effective_message
            setattr(update, field, None)
            await worker.browser_command(update, context)
            message.reply_text.assert_not_awaited()

    async def test_missing_url_is_reported_without_link(self):
        update, context = self.context(url='')
        await worker.browser_command(update, context)
        self.assertEqual(update.effective_message.reply_text.call_args.args[0],
                         'Collegamento al browser remoto non configurato.')
