"""
Official Open-Source QR Code Generator Wrapper using python 'qrcode' package.
Generates fully compliant, scannable SVG QR codes.
"""

import io
import qrcode
import qrcode.image.svg
from qrcode.constants import ERROR_CORRECT_M

class PureQRCode:
    def __init__(self, data: str):
        self.data = data

    def to_svg(self, size_px: int = 140) -> str:
        """Generate a compliant, scannable SVG QR code string."""
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(self.data)
        qr.make(fit=True)

        factory = qrcode.image.svg.SvgPathImage
        img = qr.make_image(image_factory=factory)

        stream = io.BytesIO()
        img.save(stream)
        svg_text = stream.getvalue().decode('utf-8')

        # Clean SVG attributes for responsive display
        if '<svg' in svg_text:
            svg_body = svg_text[svg_text.find('<svg'):]
            # Replace width/height with size_px
            svg_body = svg_body.replace('width="', f'data-w="', 1)
            svg_body = svg_body.replace('height="', f'data-h="', 1)
            svg_body = svg_body.replace('<svg ', f'<svg width="{size_px}" height="{size_px}" style="max-width:100%; height:auto;" ', 1)
            return svg_body
        return svg_text
