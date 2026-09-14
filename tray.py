import os
import sys
import threading
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

def create_tray_icon_image() -> Image.Image:
    """Generates a clean simple icon for the system tray dynamically."""
    image = Image.new('RGB', (64, 64), color=(30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.rectangle([16, 16, 48, 48], fill=(0, 120, 215))
    dc.text((22, 24), "GD", fill=(255, 255, 255))
    return image

class TrayDaemon:
    def __init__(self, on_open_chat: callable, on_quit: callable):
        self.on_open_chat = on_open_chat
        self.on_quit = on_quit
        self.icon = None

    def run_tray(self) -> None:
        """Starts the system tray background thread."""
        image = create_tray_icon_image()
        menu = pystray.Menu(
            item('Open Assistant', self.open_chat_action, default=True),
            pystray.Menu.SEPARATOR,
            item('Exit', self.quit_action)
        )
        # Note: Must use pystray.Icon (capital I)
        self.icon = pystray.Icon("GD Assistant", image, "GD Assistant v0.1", menu)

        # Run tray loop (blocks background thread)
        self.icon.run()

    def open_chat_action(self, icon, item) -> None:
        if self.on_open_chat:
            self.on_open_chat()

    def quit_action(self, icon, item) -> None:
        if self.icon:
            self.icon.stop()
        if self.on_quit:
            self.on_quit()

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()