"""Offline regression tests: no Telegram credentials or network required."""
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import bot
from pyrogram.errors import ApiIdInvalid, FloodWait, InternalServerError


def fake_client(loop):
    started = asyncio.Event()
    started.set()
    return SimpleNamespace(
        loop=loop, start=AsyncMock(), stop=AsyncMock(), disconnect=AsyncMock(),
        is_connected=True, is_initialized=True,
        session=SimpleNamespace(is_started=started, stop=AsyncMock()),
        storage=SimpleNamespace(conn=None, close=AsyncMock()),
        me=SimpleNamespace(username="test_bot", id=123),
    )


class BootstrapTests(unittest.TestCase):
    def test_real_client_and_handlers_share_running_loop(self):
        async def check():
            await asyncio.sleep(0)  # drain import-time handler registrations
            self.assertIs(bot.app.loop, asyncio.get_running_loop())
            self.assertTrue(bot.app.dispatcher.groups)
            task = bot.app.loop.create_task(asyncio.sleep(0, result="same-loop"))
            self.assertEqual(await task, "same-loop")
        bot._APP_LOOP.run_until_complete(check())

    def test_entrypoint_runner_uses_and_closes_client_loop(self):
        script = '''
import asyncio
import bot
async def probe():
    assert asyncio.get_running_loop() is bot.app.loop
    await asyncio.sleep(0)
    assert bot.app.dispatcher.groups
    assert await bot.app.loop.create_task(asyncio.sleep(0, result=42)) == 42
bot.main = probe
bot.run_bot()
assert bot.app.loop.is_closed()
'''
        result = subprocess.run([sys.executable, "-W", "error::RuntimeWarning", "-c", script],
                                cwd=os.path.dirname(__file__), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Task was destroyed", result.stderr)

    def test_render_runtime_pin_matches_blueprint(self):
        from pathlib import Path
        version = Path(".python-version").read_text().strip()
        self.assertIn(f"value: {version}", Path("render.yaml").read_text())
        self.assertEqual(Path("runtime.txt").read_text().strip(), f"python-{version}")

    def test_missing_and_negative_api_id_are_rejected(self):
        for value in (0, -1):
            with patch.multiple(bot, API_ID=value, API_HASH="test", BOT_TOKEN="test"):
                with self.assertRaises(SystemExit):
                    bot._validate_config()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = fake_client(asyncio.get_running_loop())
        self.client_patch = patch.object(bot, "app", self.client)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.state_patch = patch.multiple(bot, _lifecycle="starting", _connect_attempt=0)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    async def test_start_success(self):
        await bot._start_telegram()
        self.client.start.assert_awaited_once()
        self.assertEqual(bot._connect_attempt, 1)

    async def test_wrong_loop_fails_before_connecting(self):
        self.client.loop = object()
        with self.assertRaisesRegex(RuntimeError, "original event loop"):
            await bot._start_telegram()
        self.client.start.assert_not_awaited()

    async def test_transient_failure_cleans_before_retry(self):
        self.client.start.side_effect = [OSError("network down"), None]
        with patch.object(bot, "_close_telegram", new_callable=AsyncMock) as cleanup, \
             patch.object(bot.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await bot._start_telegram()
        cleanup.assert_awaited_once()
        sleep.assert_awaited_once()
        self.assertEqual(self.client.start.await_count, 2)

    async def test_server_error_retries(self):
        self.client.start.side_effect = [InternalServerError(), None]
        with patch.object(bot, "_close_telegram", new_callable=AsyncMock), \
             patch.object(bot.asyncio, "sleep", new_callable=AsyncMock):
            await bot._start_telegram()
        self.assertEqual(self.client.start.await_count, 2)

    async def test_exhaustion_does_not_sleep_again(self):
        self.client.start.side_effect = OSError("offline")
        with patch.object(bot, "CONNECT_RETRIES", 2), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock), \
             patch.object(bot.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(OSError):
                await bot._start_telegram()
        self.assertEqual(self.client.start.await_count, 2)
        sleep.assert_awaited_once()

    async def test_invalid_credentials_fail_without_retry(self):
        self.client.start.side_effect = ApiIdInvalid()
        with self.assertRaises(ApiIdInvalid):
            await bot._start_telegram()
        self.client.start.assert_awaited_once()

    async def test_programming_error_is_not_retried(self):
        self.client.start.side_effect = RuntimeError("different loop")
        with self.assertRaises(RuntimeError):
            await bot._start_telegram()
        self.client.start.assert_awaited_once()

    async def test_short_floodwait_is_respected(self):
        self.client.start.side_effect = [FloodWait(3), None]
        with patch.object(bot, "_close_telegram", new_callable=AsyncMock), \
             patch.object(bot.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await bot._start_telegram()
        sleep.assert_awaited_once_with(4)

    async def test_long_floodwait_does_not_hold_deploy_open(self):
        self.client.start.side_effect = FloodWait(120)
        with self.assertRaises(FloodWait):
            await bot._start_telegram()
        self.client.start.assert_awaited_once()

    async def test_timeout_cancels_start_and_does_not_reuse_partial_session(self):
        cancelled = asyncio.Event()
        async def hang():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.client.start.side_effect = hang
        with patch.object(bot, "CONNECT_TIMEOUT_S", 0.01):
            with self.assertRaises(TimeoutError):
                await bot._start_telegram()
        self.assertTrue(cancelled.is_set())
        self.client.start.assert_awaited_once()

    async def test_cleanup_failure_prevents_retry(self):
        self.client.start.side_effect = OSError("offline")
        with patch.object(bot, "_close_telegram", AsyncMock(side_effect=RuntimeError("dirty"))):
            with self.assertRaisesRegex(RuntimeError, "dirty"):
                await bot._start_telegram()
        self.client.start.assert_awaited_once()

    async def test_initialized_client_stops_preserving_handlers(self):
        await bot._close_telegram()
        self.client.stop.assert_awaited_once_with(clear_handlers=False)

    async def test_connected_client_disconnects(self):
        self.client.is_initialized = False
        await bot._close_telegram()
        self.client.disconnect.assert_awaited_once()

    async def test_partial_session_and_storage_close(self):
        self.client.is_initialized = self.client.is_connected = False
        self.client.storage.conn = object()
        session = self.client.session
        await bot._close_telegram()
        session.stop.assert_awaited_once()
        self.client.storage.close.assert_awaited_once()
        self.assertIsNone(self.client.session)

    async def test_health_is_unready_during_startup(self):
        response = await bot.web_handler(SimpleNamespace(path="/health"))
        self.assertEqual(response.status, 503)
        self.assertFalse(json.loads(response.text)["telegram_connected"])
        response = await bot.web_handler(SimpleNamespace(path="/"))
        self.assertEqual(response.status, 200)

    async def test_health_tracks_telegram_disconnect_and_engine(self):
        with patch.multiple(bot, _lifecycle="ready", compiled_pattern=re.compile("test")):
            for path in ("/health", "/ready"):
                response = await bot.web_handler(SimpleNamespace(path=path))
                self.assertEqual(response.status, 200)
            self.client.session.is_started.clear()
            response = await bot.web_handler(SimpleNamespace(path="/health"))
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.text)["status"], "degraded")
            self.client.session.is_started.set()
            with patch.object(bot, "compiled_pattern", None):
                response = await bot.web_handler(SimpleNamespace(path="/health"))
                self.assertEqual(response.status, 503)

    async def test_ping_is_liveness_only(self):
        response = await bot.ping_handler(SimpleNamespace())
        self.assertEqual((response.status, response.text), (200, "pong"))

    async def test_main_cleans_web_runner_after_start_failure(self):
        runner = SimpleNamespace(cleanup=AsyncMock())
        with patch.object(bot, "_validate_config"), patch.object(bot, "init_db"), \
             patch.object(bot, "load_custom_maps"), patch.object(bot, "generate_and_load_mapping"), \
             patch.object(bot, "start_web_server", AsyncMock(return_value=runner)), \
             patch.object(bot, "_start_telegram", AsyncMock(side_effect=OSError("offline"))), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock) as cleanup:
            with self.assertRaises(OSError):
                await bot.main()
        runner.cleanup.assert_awaited_once()
        cleanup.assert_awaited_once()
        self.assertEqual(bot._lifecycle, "stopped")

    async def test_signal_interrupts_startup_and_cleans_resources(self):
        loop = asyncio.get_running_loop()
        callbacks = {}
        runner = SimpleNamespace(cleanup=AsyncMock())
        async def startup():
            loop.call_soon(callbacks[signal.SIGTERM])
            await asyncio.Event().wait()
        with patch.object(loop, "add_signal_handler", side_effect=lambda s, fn: callbacks.update({s: fn})), \
             patch.object(loop, "remove_signal_handler"), patch.object(bot, "_validate_config"), \
             patch.object(bot, "init_db"), patch.object(bot, "load_custom_maps"), \
             patch.object(bot, "generate_and_load_mapping"), \
             patch.object(bot, "start_web_server", AsyncMock(return_value=runner)), \
             patch.object(bot, "_start_telegram", side_effect=startup), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock) as cleanup:
            await asyncio.wait_for(bot.main(), timeout=1)
        runner.cleanup.assert_awaited_once()
        cleanup.assert_awaited_once()

    async def test_signal_interrupts_running_bot(self):
        loop = asyncio.get_running_loop()
        callbacks = {}
        runner = SimpleNamespace(cleanup=AsyncMock())
        async def set_commands():
            loop.call_soon(callbacks[signal.SIGTERM])
        with patch.object(loop, "add_signal_handler", side_effect=lambda s, fn: callbacks.update({s: fn})), \
             patch.object(loop, "remove_signal_handler"), patch.object(bot, "_validate_config"), \
             patch.object(bot, "init_db"), patch.object(bot, "load_custom_maps"), \
             patch.object(bot, "generate_and_load_mapping"), \
             patch.object(bot, "start_web_server", AsyncMock(return_value=runner)), \
             patch.object(bot, "_start_telegram", new_callable=AsyncMock), \
             patch.object(bot, "_set_bot_commands", side_effect=set_commands), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock) as cleanup:
            await asyncio.wait_for(bot.main(), timeout=1)
        cleanup.assert_awaited_once()
        runner.cleanup.assert_awaited_once()

    async def test_web_bind_failure_cleans_runner(self):
        runner = SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock())
        site = SimpleNamespace(start=AsyncMock(side_effect=OSError("port busy")))
        with patch.object(bot.web, "AppRunner", return_value=runner), \
             patch.object(bot.web, "TCPSite", return_value=site):
            with self.assertRaises(OSError):
                await bot.start_web_server()
        runner.cleanup.assert_awaited_once()

    async def test_admin_commands_disabled_without_admin_id(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=42), reply=AsyncMock())
        with patch.object(bot, "ADMIN_ID", 0), patch.object(bot, "get_stats") as stats, \
             patch.object(bot, "get_all_user_ids") as recipients:
            await bot.stats_cmd(self.client, message)
            await bot.broadcast_cmd(self.client, message)
        stats.assert_not_called()
        recipients.assert_not_called()
        self.assertEqual(message.reply.await_count, 2)

    async def test_oversized_json_is_rejected_before_download(self):
        message = SimpleNamespace(
            document=SimpleNamespace(file_name="map.json", file_size=100 * 1024 * 1024),
            from_user=SimpleNamespace(id=42), reply=AsyncMock(), download=AsyncMock(),
        )
        with patch.object(bot, "is_rate_limited", return_value=0):
            await bot.handle_document(self.client, message)
        message.download.assert_not_awaited()
        message.reply.assert_awaited_once()


def tearDownModule():
    if not bot._APP_LOOP.is_closed():
        with asyncio.Runner(loop_factory=lambda: bot._APP_LOOP) as runner:
            runner.run(asyncio.sleep(0))
        asyncio.set_event_loop(None)
    bot.app.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
