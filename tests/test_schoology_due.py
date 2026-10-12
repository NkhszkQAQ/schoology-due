"""Offline tests: all calendars and configuration are synthetic."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/schoology-due/scripts/schoology_due.py'
spec = importlib.util.spec_from_file_location('schoology_due', SCRIPT)
due = importlib.util.module_from_spec(spec)
spec.loader.exec_module(due)


def calendar(start='DTSTART:20261014T155900Z', summary='Example homework'):
    return '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VEVENT', start,
        'SUMMARY:' + summary, 'URL:https://example.invalid/assignment/1000000001',
        'END:VEVENT', 'END:VCALENDAR', '',
    ])


class CalendarTests(unittest.TestCase):
    def test_folded_and_escaped_text(self):
        text = calendar(summary=r'Read\, reflect\; write\nPart 2').replace(
            'Part 2', 'Part\r\n 2')
        event = due.parse_ical(text)[0]
        self.assertEqual(event['SUMMARY'], 'Read, reflect; write\nPart2')

    def test_html_is_failure_not_empty_calendar(self):
        with self.assertRaises(RuntimeError):
            due.parse_ical('<html>Sign in</html>')

    def test_empty_valid_calendar(self):
        self.assertEqual(due.parse_ical('BEGIN:VCALENDAR\nEND:VCALENDAR'), [])

    def test_utc_deadline(self):
        event = due.parse_ical(calendar())[0]
        self.assertEqual(due.parse_start(event, ZoneInfo('Asia/Shanghai')).isoformat(),
                         '2026-10-14T23:59:00+08:00')

    def test_tzid_conversion(self):
        event = due.parse_ical(calendar('DTSTART;TZID=America/New_York:20261014T120000'))[0]
        self.assertEqual(due.parse_start(event, ZoneInfo('Asia/Shanghai')).hour, 0)
        self.assertEqual(due.parse_start(event, ZoneInfo('Asia/Shanghai')).day, 15)

    def test_all_day_date(self):
        event = due.parse_ical(calendar('DTSTART;VALUE=DATE:20261014'))[0]
        self.assertEqual(due.parse_start(event, ZoneInfo('Asia/Shanghai')).isoformat(),
                         '2026-10-14T00:00:00+08:00')

    def test_floating_time(self):
        event = due.parse_ical(calendar('DTSTART:20261014T120000'))[0]
        self.assertEqual(due.parse_start(event, ZoneInfo('Asia/Shanghai')).hour, 12)

    def test_course_mapping_and_unknown(self):
        event = due.parse_ical(calendar())[0]
        mapping = {'assignments': {'1000000001': 'Example Course'}, 'summaries': {}}
        self.assertEqual(due.course_for(event, mapping), 'Example Course')
        self.assertEqual(due.course_for(event, {'assignments': {}, 'summaries': {}}), '课程未标注')

    def test_week_window_includes_last_microsecond(self):
        now = datetime(2026, 10, 12, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
        args = argparse.Namespace(today=False, week=True, days=None)
        start, end, _ = due.select_window(args, now)
        self.assertEqual(start, now)
        self.assertEqual(end.isoformat(), '2026-10-19T00:00:00+08:00')
        sunday = datetime(2026, 10, 18, 23, 59, 59, 999999, tzinfo=now.tzinfo)
        self.assertTrue(start <= sunday < end)

    def test_today_includes_past_deadlines(self):
        now = datetime(2026, 10, 12, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
        args = argparse.Namespace(today=True, week=False, days=None)
        start, end, _ = due.select_window(args, now)
        self.assertEqual(start.hour, 0)
        self.assertEqual(end.day, 13)


class PrivateConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)

    def private_file(self, name, contents):
        path = self.config / name
        path.write_text(contents, encoding='utf-8')
        path.chmod(0o600)
        return path

    def test_reject_broad_permissions(self):
        path = self.private_file('ical_url', 'https://example.invalid/calendar/private-example')
        path.chmod(0o644)
        with self.assertRaises(RuntimeError):
            due.read_private_text(path)

    def test_webcal_to_https(self):
        self.private_file('ical_url', 'webcal://example.invalid/calendar/private-example')
        with patch.object(due.urllib.request, 'urlopen') as opener:
            opener.return_value.__enter__.return_value.read.return_value = calendar().encode()
            self.assertEqual(due.fetch_feed(self.config), calendar())
            self.assertEqual(opener.call_args.args[0].full_url,
                             'https://example.invalid/calendar/private-example')

    def test_network_error_redacts_link(self):
        private = 'https://example.invalid/calendar/private-example'
        self.private_file('ical_url', private)
        with patch.object(due.urllib.request, 'urlopen', side_effect=URLError(private)):
            with self.assertRaises(RuntimeError) as captured:
                due.fetch_feed(self.config)
        self.assertNotIn(private, str(captured.exception))
        self.assertIn('URLError', str(captured.exception))

    def test_http_rejected(self):
        self.private_file('ical_url', 'http://example.invalid/calendar/private-example')
        with self.assertRaises(RuntimeError):
            due.fetch_feed(self.config)

    def test_malformed_mapping_rejected(self):
        for data in ([], {'assignments': []}, {'summaries': {'Example': 1}}):
            self.private_file('course_map.json', json.dumps(data))
            with self.assertRaises(RuntimeError):
                due.load_course_map(self.config)

    def test_cli_json_end_to_end(self):
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        raw = now.replace(hour=23, minute=59, second=0).strftime('%Y%m%dT%H%M%S')
        self.private_file('ical_url', 'https://example.invalid/calendar/private-example')
        self.private_file('course_map.json', json.dumps({'assignments': {'1000000001': 'Example'}}))
        with patch.dict(os.environ, {'SCHOOLOGY_DUE_CONFIG': str(self.config)}), \
             patch('sys.argv', ['schoology_due.py', '--today', '--json']), \
             patch.object(due.urllib.request, 'urlopen') as opener:
            opener.return_value.__enter__.return_value.read.return_value = calendar('DTSTART:' + raw).encode()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(due.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['course'], 'Example')
        self.assertTrue(result['items'][0]['deadline'].endswith('+08:00'))

    def test_cli_text_offset_matches_timezone(self):
        now = datetime.now(ZoneInfo('America/New_York'))
        raw = now.replace(hour=23, minute=59, second=0).strftime('%Y%m%dT%H%M%S')
        with patch('sys.argv', ['schoology_due.py', '--today', '--timezone', 'America/New_York']), \
             patch.object(due, 'fetch_feed', return_value=calendar('DTSTART:' + raw)), \
             patch.object(due, 'load_course_map', return_value={'assignments': {}, 'summaries': {}}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(due.main(), 0)
        self.assertIn(now.strftime('%z'), output.getvalue())
        self.assertNotIn('UTC+8', output.getvalue())

    def test_cli_failure_is_not_no_assignments(self):
        with patch('sys.argv', ['schoology_due.py', '--today']), \
             patch.object(due, 'fetch_feed', return_value='<html>Login</html>'):
            output, error = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                self.assertEqual(due.main(), 1)
        self.assertNotIn('没有', output.getvalue())
        self.assertIn('iCal', error.getvalue())

    def test_invalid_timezone_no_traceback(self):
        with patch('sys.argv', ['schoology_due.py', '--today', '--timezone', 'Invalid/Zone']):
            error = io.StringIO()
            with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as captured:
                due.main()
        self.assertEqual(captured.exception.code, 2)
        self.assertNotIn('Traceback', error.getvalue())


if __name__ == '__main__':
    unittest.main()
