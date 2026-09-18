"""Offline regression tests: no Telegram credentials or network required."""
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import unittest
import tempfile
import zipfile
from pathlib import Path
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



class NameCoverageTests(unittest.TestCase):
    def setUp(self):
        self.engine = bot.NameEngine(
            {"Xiao Yan": "Arjun Sharma", "XiaoYan": "Old Alias Name", "Lin Feng": "Kabir Singh"}, {})

    def session(self, custom=None):
        return bot.TranslationSession(bot.NameEngine(
            {"Xiao Yan": "Arjun Sharma", "Lin Feng": "Kabir Singh"}, custom or {}))

    def test_all_common_spellings_have_same_identity(self):
        session = bot.TranslationSession(self.engine)
        text = "Xiao Yan|Xiaoyan|XIAO YAN|Xiao-Yan|Xiao\tYan|Xiao\nYan|Xiao\u00a0Yan|Xiao‑Yan"
        self.assertEqual(session(text), "|".join(["Arjun Sharma"] * 8))
        report = session.report()
        self.assertEqual(report["summary"]["unique_names_replaced"], 1)
        self.assertEqual(report["summary"]["total_replacements"], 8)
        self.assertEqual(len(report["characters"][0]["spellings_seen"]), 8)

    def test_generated_aliases_keep_canonical_mapping(self):
        with patch.multiple(bot, mapping_dict={}, custom_mapping_dict={}, _engine=None, compiled_pattern=None):
            bot.generate_and_load_mapping()
            self.assertEqual(bot.mapping_dict["XiaoYan"], bot.mapping_dict["Xiao Yan"])
            session = bot.TranslationSession()
            self.assertEqual(session("XiaoYan"), session("Xiao Yan"))

    def test_custom_override_case_and_joined_alias_priority(self):
        for custom_key in ("xiao yan", "XIAOYAN", "Xiao-Yan"):
            with self.subTest(custom_key=custom_key):
                session = self.session({custom_key: "Rudra Rao"})
                self.assertEqual(session("Xiao Yan xiaoyan XIAO-YAN"), "Rudra Rao Rudra Rao Rudra Rao")
                self.assertEqual(session.report()["characters"][0]["mapping_source"], "custom")

    def test_multiword_alias_longest_match_and_possessive(self):
        session = self.session({"Xiao Yan Qing": "Meera Rao", "Young Master Xiao": "Arjun Sharma"})
        self.assertEqual(session("Xiao Yan Qing met Young Master Xiao's friend."),
                         "Meera Rao met Arjun Sharma's friend.")

    def test_smart_apostrophe_and_unicode_case(self):
        session = self.session({"Lin Wan'er": "Meera Rao"})
        self.assertEqual(session("Lin Wan’er"), "Meera Rao")
        self.assertEqual(session("LİN FENG"), "Kabir Singh")

    def test_partial_words_are_not_changed(self):
        session = self.session()
        text = "AXiao Yan Xiao Yanming _XiaoYan XiaoYan_"
        self.assertEqual(session(text), text)
        self.assertEqual(session.replacements, 0)

    def test_single_pass_does_not_cascade_or_consume_null_tokens(self):
        session = self.session({"Xiao Yan": "Lin Feng"})
        self.assertEqual(session("Xiao Yan Lin Feng \x00000000\x00"),
                         "Lin Feng Kabir Singh \x00000000\x00")

    def test_sessions_snapshot_dictionary_and_isolate_counts(self):
        custom = {"Xiao Yan": "Rudra Rao"}
        engine = bot.NameEngine({}, custom)
        old_session = bot.TranslationSession(engine)
        custom["Xiao Yan"] = "Meera Rao"
        new_session = bot.TranslationSession(bot.NameEngine({}, custom))
        self.assertEqual(old_session("Xiao Yan"), "Rudra Rao")
        self.assertEqual(new_session("Xiao Yan Xiao Yan"), "Meera Rao Meera Rao")
        self.assertEqual(old_session.replacements, 1)
        self.assertEqual(new_session.replacements, 2)

    def test_unknown_review_has_context_not_automatic_replacement(self):
        session = self.session()
        self.assertEqual(session("Xiao Zoravan met 萧炎 and Xiao Yan.", "chapter 2"),
                         "Xiao Zoravan met 萧炎 and Arjun Sharma.")
        report = session.report()
        self.assertEqual({e["possible_name"] for e in report["needs_review"]}, {"Xiao Zoravan", "萧炎"})
        self.assertEqual(report["needs_review"][0]["samples"][0]["location"], "chapter 2")
        self.assertEqual(report["characters"][0]["sample_locations"], ["chapter 2"])
        json.dumps(report)

    def test_no_matches_report_does_not_claim_complete_detection(self):
        session = self.session()
        self.assertEqual(session("Alice waited."), "Alice waited.")
        report = session.report()
        self.assertEqual(report["summary"]["total_replacements"], 0)
        self.assertIn("not guaranteed", " ".join(report["notes"]))

    def test_colliding_generated_names_are_flagged_for_review(self):
        session = self.session({"Lin Feng": "Arjun Sharma"})
        session("Xiao Yan met Lin Feng.")
        self.assertEqual(session.report()["shared_replacement_names"], [{
            "replacement_name": "Arjun Sharma", "original_names": ["Xiao Yan", "Lin Feng"]}])

    def test_empty_engine_and_empty_segments(self):
        session = bot.TranslationSession(bot.NameEngine({}, {}))
        self.assertEqual(session("Hello"), "Hello")
        self.assertEqual(bot._translate_segments([], session, "empty"), [])

    def test_cross_segment_multiple_replacements_and_empty_run(self):
        session = self.session()
        segments = ["Hello Xiao ", "", "Yan and Lin ", "Feng!"]
        result = bot._translate_segments(segments, session, "paragraph 1")
        self.assertEqual("".join(result), "Hello Arjun Sharma and Kabir Singh!")
        self.assertEqual(session.replacements, 2)


class FileCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.engine = bot.NameEngine({"Xiao Yan": "Arjun Sharma", "Lin Feng": "Kabir Singh"}, {})
        patches = patch.multiple(bot, _engine=self.engine, compiled_pattern=self.engine.pattern)
        patches.start()
        self.addCleanup(patches.stop)

    def paths(self, extension):
        return self.directory / ("input" + extension), self.directory / ("output" + extension)

    def test_txt_report_utf8_bom_multiline_and_counts(self):
        source, target = self.paths(".txt")
        source.write_text("Xiao\nYan met Xiaoyan.\n\nXiao Zoravan waited.", encoding="utf-8-sig")
        report = self.directory / "character_report.json"
        self.assertTrue(bot.process_file(str(source), str(target), str(report)))
        self.assertEqual(target.read_text(), "Arjun Sharma met Arjun Sharma.\n\nXiao Zoravan waited.")
        data = json.loads(report.read_text())
        self.assertEqual(data["summary"]["total_replacements"], 2)
        self.assertEqual(data["summary"]["review_candidate_mentions"], 1)

    def test_invalid_utf8_and_unsupported_file_fail_explicitly(self):
        source, target = self.paths(".txt")
        source.write_bytes(b"Xiao Yan\xff")
        with self.assertLogs("NovelBot", level="ERROR"):
            self.assertFalse(bot.process_file(str(source), str(target)))
        self.assertFalse(bot.process_file("input.pdf", str(target)))

    def test_docx_split_runs_nested_tables_and_header_footer(self):
        source, target = self.paths(".docx")
        document = bot.docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run("Hello Xiao ").bold = True
        paragraph.add_run("Yan!").italic = True
        cell = document.add_table(rows=1, cols=1).cell(0, 0)
        cell.add_table(rows=1, cols=1).cell(0, 0).text = "Lin Feng"
        document.sections[0].header.paragraphs[0].text = "Xiao Yan"
        document.sections[0].footer.add_table(rows=1, cols=1, width=1000).cell(0, 0).text = "Lin Feng"
        document.save(source)
        session = bot.TranslationSession(self.engine)
        bot.process_docx(source, target, session)
        result = bot.docx.Document(target)
        paragraph = result.paragraphs[0]
        self.assertEqual(paragraph.text, "Hello Arjun Sharma!")
        self.assertTrue(paragraph.runs[0].bold)
        self.assertTrue(paragraph.runs[1].italic)
        self.assertEqual(result.tables[0].cell(0, 0).tables[0].cell(0, 0).text, "Kabir Singh")
        self.assertEqual(result.sections[0].header.paragraphs[0].text, "Arjun Sharma")
        self.assertEqual(result.sections[0].footer.tables[0].cell(0, 0).text, "Kabir Singh")
        self.assertEqual(session.replacements, 4)

    def test_docx_drawings_and_fields_are_not_deleted(self):
        source, target = self.paths(".docx")
        document = bot.docx.Document()
        run = document.add_paragraph().add_run("Xiao Yan")
        for tag in ("w:drawing", "w:fldChar"):
            run._r.append(bot.docx.oxml.OxmlElement(tag))
        document.save(source)
        bot.process_docx(source, target)
        result = bot.docx.Document(target)
        self.assertEqual(result.paragraphs[0].text, "Arjun Sharma")
        self.assertEqual(len(result.paragraphs[0]._p.xpath(".//w:drawing")), 1)
        self.assertEqual(len(result.paragraphs[0]._p.xpath(".//w:fldChar")), 1)

    def test_docx_merged_cells_and_linked_headers_count_once(self):
        source, target = self.paths(".docx")
        document = bot.docx.Document()
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).merge(table.cell(0, 1)).text = "Xiao Yan"
        document.sections[0].header.paragraphs[0].text = "Xiao Yan"
        document.add_section()
        document.save(source)
        session = bot.TranslationSession(self.engine)
        bot.process_docx(source, target, session)
        self.assertEqual(session.replacements, 2)

    def test_html_inline_names_preserve_attributes_scripts_and_comments(self):
        content = '<p id="Xiao Yan">Xiao <b>Yan</b> met Lin Feng.</p><script>Xiao Yan</script>' \
                  '<pre><span>Xiao Yan</span></pre><!-- Xiao Yan --><a href="Xiao Yan.html">link</a>'
        session = bot.TranslationSession(self.engine)
        result = bot.BeautifulSoup(bot.translate_markup(content, session, "chapter"), "html.parser")
        self.assertEqual(result.p.get_text(), "Arjun Sharma met Kabir Singh.")
        self.assertEqual(result.p["id"], "Xiao Yan")
        self.assertEqual(result.a["href"], "Xiao Yan.html")
        self.assertEqual(result.script.string, "Xiao Yan")
        self.assertEqual(result.pre.get_text(), "Xiao Yan")
        self.assertIn("<!-- Xiao Yan -->", str(result))
        self.assertEqual(session.replacements, 2)

    def test_html_block_boundaries_are_not_joined_into_names(self):
        session = bot.TranslationSession(self.engine)
        result = bot.translate_markup('<p>Xiao </p><p>Yan</p><p>Xiao <br/>Yan</p>', session, "test")
        self.assertNotIn("Arjun", result)
        self.assertEqual(session.replacements, 0)

    def test_epub_preserves_links_mimetype_binary_and_namespace(self):
        source, target = self.paths(".epub")
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("chapter.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                             '<p>Xiao <b>Yan</b></p><a href="Xiao Yan.xhtml">next</a></body></html>')
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr("image.bin", b"Xiao Yan\x00\xff")
        session = bot.TranslationSession(self.engine)
        bot.process_epub(source, target, session)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.namelist()[0], "mimetype")
            self.assertEqual(archive.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(archive.read("image.bin"), b"Xiao Yan\x00\xff")
            soup = bot.BeautifulSoup(archive.read("chapter.xhtml"), "xml")
            self.assertEqual(soup.p.get_text(), "Arjun Sharma")
            self.assertEqual(soup.a["href"], "Xiao Yan.xhtml")
            self.assertEqual(soup.html["xmlns"], "http://www.w3.org/1999/xhtml")
        self.assertEqual(session.replacements, 1)


class StartupOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_binds_before_database_engine_and_telegram(self):
        events = []
        runner = SimpleNamespace(cleanup=AsyncMock())
        async def bind():
            events.append("http")
            return runner
        async def fail_start():
            events.append("telegram")
            raise OSError("offline")
        with patch.object(bot, "app", fake_client(asyncio.get_running_loop())), \
             patch.object(bot, "_validate_config"), \
             patch.object(bot, "start_web_server", side_effect=bind), \
             patch.object(bot, "init_db", side_effect=lambda: events.append("database")), \
             patch.object(bot, "load_custom_maps", side_effect=lambda: events.append("custom")), \
             patch.object(bot, "generate_and_load_mapping", side_effect=lambda: events.append("engine")), \
             patch.object(bot, "_start_telegram", side_effect=fail_start), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock):
            with self.assertRaises(OSError):
                await bot.main()
        self.assertEqual(events, ["http", "database", "custom", "engine", "telegram"])
        runner.cleanup.assert_awaited_once()

    async def test_stage_progression_and_health_expose_stage(self):
        stages = []
        runner = SimpleNamespace(cleanup=AsyncMock())
        original = bot._set_stage
        def record(stage):
            original(stage)
            stages.append(stage)
        async def fail_start():
            response = await bot.web_handler(SimpleNamespace(path="/health"))
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.text)["stage"], "connect_telegram")
            raise OSError("offline")
        with patch.object(bot, "app", fake_client(asyncio.get_running_loop())), \
             patch.object(bot, "_validate_config"), patch.object(bot, "_set_stage", side_effect=record), \
             patch.object(bot, "start_web_server", AsyncMock(return_value=runner)), \
             patch.object(bot, "init_db"), patch.object(bot, "load_custom_maps"), \
             patch.object(bot, "generate_and_load_mapping"), \
             patch.object(bot, "_start_telegram", side_effect=fail_start), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock):
            with self.assertRaises(OSError):
                await bot.main()
        self.assertEqual(stages, ["bind_http", "init_database", "build_name_engine", "connect_telegram"])
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_coro().__name__ == "_startup_heartbeat"])

    async def test_startup_heartbeat_logs_stage_and_is_cancelled_when_ready(self):
        loop = asyncio.get_running_loop()
        callbacks = {}
        runner = SimpleNamespace(cleanup=AsyncMock())
        async def set_commands():
            # Fire SIGTERM only after main() has marked itself ready.
            loop.call_later(0.02, callbacks[signal.SIGTERM])
        async def slow_connect():
            await asyncio.sleep(0.05)
        with patch.object(bot, "STARTUP_HEARTBEAT_S", 0.01), \
             patch.object(bot, "app", fake_client(loop)), \
             patch.object(loop, "add_signal_handler", side_effect=lambda s, fn: callbacks.update({s: fn})), \
             patch.object(loop, "remove_signal_handler"), patch.object(bot, "_validate_config"), \
             patch.object(bot, "init_db"), patch.object(bot, "load_custom_maps"), \
             patch.object(bot, "generate_and_load_mapping"), \
             patch.object(bot, "start_web_server", AsyncMock(return_value=runner)), \
             patch.object(bot, "_start_telegram", side_effect=slow_connect), \
             patch.object(bot, "_set_bot_commands", side_effect=set_commands), \
             patch.object(bot, "_close_telegram", new_callable=AsyncMock), \
             self.assertLogs(bot.logger, level="WARNING") as logs:
            await asyncio.wait_for(bot.main(), timeout=2)
        self.assertTrue(any("Still starting: stage=connect_telegram" in line for line in logs.output))
        self.assertEqual(bot._startup_stage, "ready")
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_coro().__name__ == "_startup_heartbeat"])

    def test_stdout_is_line_buffered_without_u_flag(self):
        script = "import sys; sys.path.insert(0, '.'); import bot; print(sys.stdout.line_buffering)"
        result = subprocess.run([sys.executable, "-c", script], cwd=os.path.dirname(__file__),
                                capture_output=True, text=True,
                                env={**os.environ, "PYTHONUNBUFFERED": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "True")

    async def test_configured_port_binds_all_interfaces(self):
        runner = SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock())
        site = SimpleNamespace(start=AsyncMock())
        with patch.dict(os.environ, {"PORT": "12345"}), \
             patch.object(bot.web, "AppRunner", return_value=runner), \
             patch.object(bot.web, "TCPSite", return_value=site) as factory:
            self.assertIs(await bot.start_web_server(), runner)
        factory.assert_called_once_with(runner, "0.0.0.0", 12345)
        site.start.assert_awaited_once()

    async def test_invalid_ports_fail_fast(self):
        for port in ("bad", "0", "65536", "-1", ""):
            with self.subTest(port=port), patch.dict(os.environ, {"PORT": port}):
                with self.assertRaises(ValueError):
                    await bot.start_web_server()

    async def test_file_handler_sends_report_and_cleans_files(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            status = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
            captured = []
            async def download(**kwargs):
                Path(kwargs["file_name"]).write_text("Xiao Yan met Xiao Zoravan.")
            async def upload(path, **kwargs):
                captured.append((Path(path).name, Path(path).read_text()))
            message = SimpleNamespace(
                document=SimpleNamespace(file_name="novel.txt", file_size=50),
                from_user=SimpleNamespace(id=42, username="reader", first_name="Reader"),
                id=10, chat=SimpleNamespace(id=42), reply=AsyncMock(return_value=status),
                download=AsyncMock(side_effect=download), reply_document=AsyncMock(side_effect=upload),
            )
            client = SimpleNamespace(send_chat_action=AsyncMock())
            engine = bot.NameEngine({"Xiao Yan": "Arjun Sharma"}, {})
            with patch.multiple(bot, DOWNLOAD_DIR=directory, _engine=engine, compiled_pattern=engine.pattern), \
                 patch.object(bot, "is_rate_limited", return_value=0), \
                 patch.object(bot, "add_user"), patch.object(bot, "increment_user_stats") as stats:
                await bot.handle_document(client, message)
            self.assertEqual(len(captured), 2)
            self.assertIn("Arjun Sharma", captured[0][1])
            self.assertTrue(captured[1][0].endswith(".character_report.json"))
            self.assertEqual(json.loads(captured[1][1])["summary"]["total_replacements"], 1)
            self.assertEqual(list(Path(directory).iterdir()), [])
            stats.assert_called_once_with(42)
            status.delete.assert_awaited_once()

def tearDownModule():
    if not bot._APP_LOOP.is_closed():
        with asyncio.Runner(loop_factory=lambda: bot._APP_LOOP) as runner:
            runner.run(asyncio.sleep(0))
        asyncio.set_event_loop(None)
    bot.app.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
