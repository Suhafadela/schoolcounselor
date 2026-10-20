"""Right-to-left (Hebrew / Arabic) text support for ReportLab PDFs.

ReportLab has no bidi support, so we do the layout ourselves: the logical text
is wrapped into lines first (in reading order), and only then is each line
converted to visual order. Converting the whole paragraph first and letting
ReportLab wrap it afterwards is what scrambles line order in long paragraphs.
"""
import os

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable

FONT_REGULAR = 'NotoMerged'
FONT_BOLD = 'NotoMerged-Bold'
_fonts_ready = False


def register_fonts(base_dir):
    """Register the bundled Hebrew+Arabic font. Returns (regular, bold) names."""
    global _fonts_ready
    if not _fonts_ready:
        try:
            reg = os.path.join(base_dir, 'fonts', 'NotoMerged-Regular.ttf')
            bold = os.path.join(base_dir, 'fonts', 'NotoMerged-Bold.ttf')
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, reg))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
            _fonts_ready = True
        except Exception:
            return 'Helvetica', 'Helvetica-Bold'
    return FONT_REGULAR, FONT_BOLD


def _shape(text):
    try:
        import arabic_reshaper
        return arabic_reshaper.reshape(text)
    except Exception:
        return text


def _visual(line):
    """Convert one logical line to visual order (right-to-left base direction)."""
    try:
        from bidi.algorithm import get_display
        return get_display(line, base_dir='R')
    except Exception:
        return line


def wrap_rtl(text, font, size, width):
    """Wrap logical text into lines that fit `width`, each in visual order."""
    out = []
    width_of = lambda s: pdfmetrics.stringWidth(s, font, size)
    for para in str(text).replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        para = para.strip()
        if not para:
            out.append('')
            continue
        words = _shape(para).split()
        line = ''
        for word in words:
            candidate = word if not line else line + ' ' + word
            if width_of(candidate) <= width or not line:
                line = candidate
                # a single over-long word: break it by characters
                while width_of(line) > width and len(line) > 1:
                    cut = len(line) - 1
                    while cut > 1 and width_of(line[:cut]) > width:
                        cut -= 1
                    out.append(_visual(line[:cut]))
                    line = line[cut:]
            else:
                out.append(_visual(line))
                line = word
        if line:
            out.append(_visual(line))
    return out


class RTLText(Flowable):
    """A right-to-left text block that wraps and splits across pages."""

    def __init__(self, text, font, size=10, color=colors.black, leading=None,
                 align='RIGHT', space_after=0, lines=None):
        super().__init__()
        self.text = text or ''
        self.font = font
        self.size = size
        self.color = color
        self.leading = leading or size * 1.45
        self.align = align
        self.space_after = space_after
        self.lines = lines
        self._avail = None

    def _layout(self, avail_width):
        if self.lines is None or self._avail != avail_width:
            self.lines = wrap_rtl(self.text, self.font, self.size, avail_width)
            self._avail = avail_width
        return self.lines

    def wrap(self, availWidth, availHeight):
        lines = self._layout(availWidth)
        self.width = availWidth
        self.height = max(len(lines), 1) * self.leading + self.space_after
        return self.width, self.height

    def split(self, availWidth, availHeight):
        lines = self._layout(availWidth)
        fit = int(availHeight // self.leading)
        if len(lines) <= fit or fit < 1:
            return []
        first = RTLText(self.text, self.font, self.size, self.color, self.leading,
                        self.align, 0, lines[:fit])
        first._avail = availWidth
        rest = RTLText(self.text, self.font, self.size, self.color, self.leading,
                       self.align, self.space_after, lines[fit:])
        rest._avail = availWidth
        return [first, rest]

    def draw(self):
        c = self.canv
        c.setFont(self.font, self.size)
        c.setFillColor(self.color)
        y = self.height - self.space_after - self.size * 1.05
        for line in self._layout(self._avail or self.width):
            if self.align == 'LEFT':
                c.drawString(0, y, line)
            elif self.align == 'CENTER':
                c.drawCentredString(self.width / 2.0, y, line)
            else:
                c.drawRightString(self.width, y, line)
            y -= self.leading
