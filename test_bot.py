import unittest
from unittest.mock import patch, MagicMock
from bot import start, authenticate, two_factor_auth, main_menu, handle_message, exit_bot, AUTH, TWO_FACTOR, MAIN_MENU, ConversationHandler

class TestBot(unittest.TestCase):
    @patch('bot.Update')
    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_start(self, mock_update, mock_context):
        mock_update.message.from_user.username = "test_user"
        mock_update.message.from_user.first_name = "Test"
        mock_update.message.reply_text = MagicMock()

        result = await start(mock_update, mock_context)
        self.assertEqual(result, AUTH)

    @patch('bot.Update')
    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_authenticate_valid(self, mock_update, mock_context):
        mock_update.message.text = "12345"
        mock_update.message.from_user.username = "test_user"
        mock_update.message.from_user.first_name = "Test"
        mock_update.message.reply_text = MagicMock()
        mock_context.user_data = {}

        result = await authenticate(mock_update, mock_context)
        self.assertEqual(result, TWO_FACTOR)

    @patch('bot.Update')
    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_two_factor_auth_valid(self, mock_update, mock_context):
        mock_update.message.text = "123456"
        mock_update.message.from_user.username = "test_user"
        mock_update.message.from_user.first_name = "Test"
        mock_update.message.reply_text = MagicMock()
        mock_context.user_data = {'two_factor_code': '123456'}

        result = await two_factor_auth(mock_update, mock_context)
        self.assertEqual(result, MAIN_MENU)

    @patch('bot.Update')
    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_main_menu(self, mock_update, mock_context):
        mock_update.message.reply_text = MagicMock()
        mock_context.user_data = {}

        result = await main_menu(mock_update, mock_context)
        self.assertEqual(result, MAIN_MENU)

    @patch('bot.Update')
    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_handle_message_back(self, mock_update, mock_context):
        mock_update.message.text = "Назад"
        mock_update.message.from_user.username = "test_user"
        mock_update.message.reply_text = MagicMock()
        mock_context.user_data = {'path': ['section1'], 'authenticated': True}

        await handle_message(mock_update, mock_context)
        self.assertEqual(mock_context.user_data['path'], [])

    @patch('bot.Update')
    @patch('bot.ContextTypes.DEFAULT_TYPE')
    async def test_exit_bot(self, mock_update, mock_context):
        mock_update.message.from_user.username = "test_user"
        mock_update.message.reply_text = MagicMock()
        mock_context.user_data = {'authenticated': True, 'hashed_number': 'hash123'}

        result = await exit_bot(mock_update, mock_context)
        self.assertEqual(result, ConversationHandler.END)

if __name__ == '__main__':
    unittest.main()