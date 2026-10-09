"""Tests for the CTP500 app. No printer needed: the Bluetooth connection is swapped for a fake one.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import io
import sys
import tkinter
import unittest
from unittest import mock

import PIL.Image
import PIL.ImageOps

import CTP500_GUI_app_Github_Export as app

STATUS = b"HV=V1.0A,SV=V1.01,VOLT=4046mv,DPI=384,"  # what a real CTP500 answers to the status request
STATUS_REQUEST = b"\x1e\x47\x03"
JOB_START = b"\x1b\x40" + b"\x1d\x49\xf0\x19"  # initialize + start print sequence
RASTER = b"\x1d\x76\x30\x00"  # GS v 0: an image follows
FEED = b"\x0a\x0a\x0a\x9a"  # end sequence, feeds the paper out
WIDTH = app.printerWidth


class FakePrinter:
    """Stands in for the Bluetooth connection and records everything the app sends."""
    connections = []
    refuse = False  # True = printer switched off

    def __init__(self, address):
        if FakePrinter.refuse:
            raise OSError("printer is off")
        self.address, self.sent, self.closed, self.broken = address, b"", False, False
        FakePrinter.connections.append(self)

    def send(self, data):
        if self.broken:
            raise OSError("link dropped")
        self.sent += bytes(data)
        return len(data)

    def recv(self, size):
        return STATUS[:size]

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class FakePrinterTestCase(unittest.TestCase):
    """Swaps in the fake printer, a fresh connection object and no sleeps between print steps."""

    def setUp(self):
        FakePrinter.connections = []
        self.addCleanup(setattr, FakePrinter, "refuse", False)  # don't leak "printer is off" into later tests
        for name, value in (("open_connection", FakePrinter), ("sleep", lambda seconds: None), ("printer", app.PrinterConnect())):
            patcher = mock.patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


def ink_margins(img):
    """Blank pixels left and right of the ink on a prepared (1-bit, printer-width) image."""
    left, _, right, _ = PIL.ImageOps.invert(img.convert("L")).getbbox()  # via "L" like printImage: padding in a 1-bit image can be stored as 1, not 255
    return left, img.width - right


def raster_size(sent):
    """Width and height of the first image in the bytes sent to the printer."""
    header = sent.index(RASTER) + len(RASTER)
    return int.from_bytes(sent[header:header + 2], "little") * 8, int.from_bytes(sent[header + 2:header + 4], "little")


class RenderingTests(unittest.TestCase):
    font = app.system_fonts.get(app.default_font, "no-such-font.ttf")  # falls back to Pillow's font if the system has no default

    def render(self, text, size=28, align="left"):
        return app.prepare_image(app.create_text(text, self.font, size, align))

    def test_alignment_puts_text_where_asked(self):
        for size in app.font_size_options.values():
            for align in app.justification_options:
                with self.subTest(size=size, align=align):
                    img = self.render("Buy milk\nand eggs", size, align)
                    self.assertEqual(img.width, WIDTH)
                    left, right = ink_margins(img)
                    if align == "left":
                        self.assertLessEqual(left, 4)
                    elif align == "right":
                        self.assertLessEqual(right, 4)
                    else:
                        self.assertLessEqual(abs(left - right), 4)

    def test_bigger_size_makes_taller_text(self):
        heights = [self.render("Hello", size).height for size in app.font_size_options.values()]
        self.assertEqual(heights, sorted(heights))
        self.assertLess(heights[0], heights[-1])

    def test_long_text_wraps_to_paper_width(self):
        one_line = self.render("word")
        wrapped = self.render("word " * 40)
        self.assertEqual(wrapped.width, WIDTH)
        self.assertGreater(wrapped.height, 3 * one_line.height)

    def test_missing_font_falls_back_instead_of_crashing(self):
        img = app.create_text("Hello", "definitely-not-a-font.ttf")
        self.assertIsNotNone(img.getbbox())

    def test_prepare_image_scales_and_pads_to_printer_width(self):
        wide = app.prepare_image(PIL.Image.new("RGB", (WIDTH * 2, 100), "white"))
        narrow = app.prepare_image(PIL.Image.new("RGB", (100, 50), "white"))
        self.assertEqual((wide.size, wide.mode), ((WIDTH, 50), "1"))
        self.assertEqual((narrow.size, narrow.mode), ((WIDTH, 50), "1"))

    def test_print_image_sends_inverted_raster(self):
        sock = FakePrinter("test")
        img = PIL.Image.new("1", (WIDTH, 2), "white")
        img.paste(0, (0, 1, WIDTH, 2))  # second row black
        app.printImage(sock, img)
        self.assertEqual(sock.sent[:4], RASTER)
        self.assertEqual(raster_size(sock.sent), (WIDTH, 2))
        rows = sock.sent[8:]
        self.assertEqual(rows, b"\x00" * (WIDTH // 8) + b"\xff" * (WIDTH // 8))  # printer: 1 = burn a dot

    def test_can_print_text_rejects_non_fonts(self):
        self.assertFalse(app.can_print_text("no-such-font.ttf"))
        self.assertFalse(app.can_print_text(__file__))

    @unittest.skipUnless(app.default_font, "no default font on this system")
    def test_can_print_text_accepts_default_font(self):
        self.assertTrue(app.can_print_text(app.system_fonts[app.default_font]))


class ConnectionTests(FakePrinterTestCase):
    def test_connect_checks_printer_status(self):
        self.assertTrue(app.printer.connect("AA:BB:CC:DD:EE:FF"))
        self.assertTrue(app.printer.connected)
        self.assertEqual(FakePrinter.connections[0].address, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(FakePrinter.connections[0].sent, STATUS_REQUEST)

    def test_failed_connect_raises_and_stays_disconnected(self):
        FakePrinter.refuse = True
        with self.assertRaises(OSError):
            app.printer.connect("AA:BB:CC:DD:EE:FF")
        self.assertFalse(app.printer.connected)
        self.assertIsNone(app.printer.socket)

    def test_disconnect_closes_the_connection(self):
        app.printer.connect("AA:BB:CC:DD:EE:FF")
        app.printer.disconnect()
        self.assertFalse(app.printer.connected)
        self.assertTrue(FakePrinter.connections[0].closed)


class CliTests(FakePrinterTestCase):
    def cli(self, *argv, stdin=""):
        """Runs the CLI like `python app.py *argv`, returning (exit code, stdout, stderr)."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["ctp500", *argv]), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin) if isinstance(stdin, str) else stdin), \
                mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            code = app.run_cli()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_prints_text_arguments_then_disconnects(self):
        code, out, err = self.cli("Hello", "world")
        self.assertEqual(code, 0)
        [conn] = FakePrinter.connections
        self.assertEqual(conn.address, app.mac_address)
        self.assertTrue(conn.sent.startswith(STATUS_REQUEST + JOB_START + RASTER))
        self.assertTrue(conn.sent.endswith(FEED))
        self.assertTrue(conn.closed)
        self.assertEqual(out, "")  # status chatter goes to stderr, keeping stdout clean for scripts
        self.assertIn("Connection established", err)

    def test_dash_reads_all_of_stdin_as_one_printout(self):
        code, _, _ = self.cli("-", stdin="line one\nline two\nline three\n")
        self.assertEqual(code, 0)
        self.assertEqual(FakePrinter.connections[0].sent.count(RASTER), 1)

    def test_size_align_and_address_options(self):
        code, _, _ = self.cli("--size", "large", "--align", "right", "--address", "11:22:33:44:55:66", "Hi")
        self.assertEqual(code, 0)
        self.assertEqual(FakePrinter.connections[0].address, "11:22:33:44:55:66")

    def test_prints_an_image(self):
        with mock.patch.object(app.PIL.Image, "open", return_value=PIL.Image.new("RGB", (WIDTH * 2, 40), "black")):
            code, _, _ = self.cli("--image", "picture.png")
        self.assertEqual(code, 0)
        self.assertEqual(raster_size(FakePrinter.connections[0].sent), (WIDTH, 20))

    def test_follow_prints_each_line_on_one_connection(self):
        code, _, _ = self.cli("--follow", stdin="event 1\n\nevent 2\nevent 3\n")
        self.assertEqual(code, 0)
        [conn] = FakePrinter.connections
        self.assertEqual(conn.sent.count(RASTER), 3)  # blank line skipped
        self.assertEqual(conn.sent.count(FEED), 3)
        self.assertTrue(conn.closed)

    def test_follow_no_feed_feeds_once_at_the_end(self):
        code, _, _ = self.cli("--follow", "--no-feed", stdin="a\nb\nc\n")
        self.assertEqual(code, 0)
        sent = FakePrinter.connections[0].sent
        self.assertEqual(sent.count(RASTER), 3)
        self.assertEqual(sent.count(FEED), 1)
        self.assertTrue(sent.endswith(FEED))

    def test_no_feed_one_shot_never_feeds(self):
        self.cli("--no-feed", "hello")
        self.assertNotIn(FEED, FakePrinter.connections[0].sent)

    def test_follow_reconnects_when_the_printer_drops(self):
        def events():
            yield "event 1\n"
            FakePrinter.connections[-1].broken = True  # printer drops between events
            yield "event 2\n"
        code, _, err = self.cli("--follow", stdin=events())
        self.assertEqual(code, 0)
        first, second = FakePrinter.connections
        self.assertEqual((first.sent.count(RASTER), second.sent.count(RASTER)), (1, 1))
        self.assertIn("link dropped", err)

    def test_ctrl_c_stops_follow_cleanly(self):
        def events():
            yield "event 1\n"
            raise KeyboardInterrupt
        code, _, _ = self.cli("--follow", "--no-feed", stdin=events())
        self.assertEqual(code, 0)
        self.assertTrue(FakePrinter.connections[0].sent.endswith(FEED))  # last lines still fed out
        self.assertTrue(FakePrinter.connections[0].closed)

    def test_printer_off_exits_with_error(self):
        FakePrinter.refuse = True
        code, _, err = self.cli("hello")
        self.assertEqual(code, 1)
        self.assertEqual(err.count("Printing failed: printer is off"), 2)  # tried twice, then gave up

    def test_bad_input_is_a_usage_error(self):
        for argv, stdin in ((["--font", "No Such Font", "hi"], ""), (["-"], "   \n"), (["--image", "no-such-image.png"], "")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as exit:
                self.cli(*argv, stdin=stdin)
            self.assertEqual(exit.exception.code, 2)
        self.assertEqual(FakePrinter.connections, [])

    def test_list_fonts(self):
        code, out, _ = self.cli("--list-fonts")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), sorted(out.splitlines(), key=str.lower))


class GuiTests(FakePrinterTestCase):
    @classmethod
    def setUpClass(cls):  # one window for all GUI tests: Tk on macOS crashes if a second root window is created
        try:
            with mock.patch.object(tkinter.Tk, "mainloop"):
                app.run_gui()
        except tkinter.TclError as e:
            raise unittest.SkipTest(f"no display: {e}")
        cls.addClassCleanup(app.root.destroy)

    def test_font_picker_hides_fonts_that_cannot_print_text(self):
        fonts = app.fontPicker["values"]
        self.assertTrue(all(app.can_print_text(app.system_fonts[name]) for name in fonts))
        self.assertEqual(app.fontPicker.get(), app.default_font)

    def test_connect_preview_and_print(self):
        app.connect_from_gui()
        self.assertTrue(app.printer.connected)

        app.textInputField.insert("1.0", "Hello from the GUI")
        app.radioJustification_status.set(1)  # center
        app.print_from_entry()
        app.root.update()
        preview = [w for w in app.root.winfo_children() if isinstance(w, tkinter.Toplevel)][-1]
        buttons = {b["text"]: b for frame in preview.winfo_children() for b in frame.winfo_children() if isinstance(b, tkinter.Button)}
        buttons["Print"].invoke()
        app.root.update()

        self.assertFalse(preview.winfo_exists())  # preview closes once printed
        self.assertEqual(FakePrinter.connections[0].sent.count(RASTER), 1)


if __name__ == "__main__":
    unittest.main()
