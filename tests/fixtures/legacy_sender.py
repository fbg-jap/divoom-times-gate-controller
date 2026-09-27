# Frozen reference: working app v0.1.3; do not modernize this oracle.
import base64
import io
import time
from typing import List
import requests
from PIL import Image, ImageSequence
SCREEN_COUNT = 5
IMG_SIZE = 128

class DivoomSender:

    @staticmethod
    def lcd_array(screen: int) -> List[int]:
        arr = [0] * SCREEN_COUNT
        arr[screen - 1] = 1
        return arr

    @staticmethod
    def resize_image(img: Image.Image) -> Image.Image:
        return img.convert('RGB').resize((IMG_SIZE, IMG_SIZE), Image.LANCZOS)

    @staticmethod
    def load_frames(path: str) -> List[Image.Image]:
        img = Image.open(path)
        if getattr(img, 'is_animated', False):
            return [frame.convert('RGB') for frame in ImageSequence.Iterator(img)]
        return [img.convert('RGB')]

    @classmethod
    def send_to_screen(cls, ip: str, screen: int, path: str, quality: int, speed: int, timeout: int=10) -> None:
        frames = [cls.resize_image(f) for f in cls.load_frames(path)]
        pic_id = int(time.time())
        lcd = cls.lcd_array(screen)
        for offset, frame in enumerate(frames):
            buf = io.BytesIO()
            frame.save(buf, format='JPEG', quality=quality)
            payload = {'Command': 'Draw/SendHttpGif', 'LcdArray': lcd, 'PicNum': len(frames), 'PicOffset': offset, 'PicID': pic_id, 'PicSpeed': speed, 'PicWidth': IMG_SIZE, 'PicData': base64.b64encode(buf.getvalue()).decode()}
            r = requests.post(f'http://{ip}/post', json=payload, timeout=timeout)
            r.raise_for_status()
            body = r.json()
            if body.get('error_code') != 0:
                raise RuntimeError(f'Divoom rejected frame {offset + 1}: {body}')
            time.sleep(0.1)
