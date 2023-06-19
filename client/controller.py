import subprocess
import socket
import threading

from pynput import keyboard
import requests

from models.http_bearer import HTTPBearer

from config import (
    BACKEND_IP,
    BACKEND_URL,
)

from logger_setup import log


class Controller:
    def __init__(
        self,
        port: int,
        relay_name: str,
        drone_name: str,
        HTTPAuthentication: HTTPBearer
    ) -> None:

        self.HTTPAuthentication: HTTPBearer = HTTPAuthentication
        self.relay = relay_name
        self.drone = drone_name
        self.port = port
        self.address = ('', 6969)  # Localhost
        self.backend_address = (BACKEND_IP, self.port)

        self.status = None  # Will be a string when updated

        # Controller/Key Mapping Variables

        self.for_back_velocity = 0
        self.left_right_velocity = 0
        self.up_down_velocity = 0
        self.yaw_velocity = 0
        self.vel_speed = 80

        self.key_mapping = {
            'w': (1, 0, 0, 0),
            's': (-1, 0, 0, 0),
            'a': (0, -1, 0, 0),
            'd': (0, 1, 0, 0),
            'space': (0, 0, 1, 0),
            'shift': (0, 0, -1, 0),
            'q': (0, 0, 0, -1),
            'e': (0, 0, 0, 1),
            't': (0, 0, 0, 0),
            'l': (0, 0, 0, 0),
        }

        self.key_mapping_release = {
            'w': (-1, 0, 0, 0),
            's': (1, 0, 0, 0),
            'a': (0, 1, 0, 0),
            'd': (0, -1, 0, 0),
            'space': (0, 0, -1, 0),
            'shift': (0, 0, 1, 0),
            'q': (0, 0, 0, 1),
            'e': (0, 0, 0, -1),
            't': (0, 0, 0, 0),
            'l': (0, 0, 0, 0),
        }

        self.pressed_keys = set()

        self.handle()

    def handle(self) -> None:
        announcement_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        announcement_socket.bind(self.backend_address)
        announcement_socket.settimeout(3)

        verified = False
        count = 0
        connection = None

        # Await Backend Verification
        while not verified:
            try:
                announcement_socket.send(b'Hello backend!')

            except socket.error as exception:
                log.error(f'Could not send RTS: {exception}')

            try:
                connection, _ = announcement_socket.recvfrom(2048)

            except TimeoutError as exception:
                count += 1
                log.error(f"Socket Error: {exception} \nRetrying RTS")

            if count >= 10:
                log.critical("Could Not Verify With Backend")
                return

            if connection:
                log.debug("Verification Complete")
                verified = True

        # Close the socket to allow use from FFMPEG.
        announcement_socket.close()

        # Start the Video Process
        threading.Thread(
            name='VideoStream',
            target=self.video
        ).start()

        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

    def video(self) -> None:
        log.info("Starting Video Process...")
        ffm_config = [
            'C:/Users/chris/Documents/Comtek/ffmpeg-master-latest-win64-gpl/bin/ffplay',
            '-i', f'udp://0.0.0.0:6969',
            '-probesize', '32',
            '-framerate', '30',
            '-fflags', 'nobuffer',
            '-flags', 'low_delay',
            '-framedrop',
            '-strict', 'experimental',
            '-loglevel', 'panic'
        ]

        self.process = subprocess.Popen(
            ffm_config,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE
        )

    def update_velocity(self, key_char, mapping) -> None:
        # Check input
        if key_char == 'w' or key_char == 's':
            self.for_back_velocity += self.vel_speed * mapping[key_char][0]

        elif key_char == 'a' or key_char == 'd':
            self.left_right_velocity += self.vel_speed * mapping[key_char][1]

        elif key_char == 'space' or key_char == 'shift':
            self.up_down_velocity += self.vel_speed * mapping[key_char][2]

        elif key_char == 'q' or key_char == 'e':
            self.yaw_velocity += self.vel_speed * mapping[key_char][3]

        elif key_char == 't':
            query = {'name': self.drone, 'parent': self.relay}
            response = requests.post(
                f'{BACKEND_URL}/drone/takeoff', json=query, auth=self.HTTPAuthentication)
            log.info("Takeoff: ", response.json())
            return

        elif key_char == 'l':
            query = {'name': self.drone, 'parent': self.relay}
            response = requests.post(
                f'{BACKEND_URL}/drone/land', json=query, auth=self.HTTPAuthentication)
            log.info("Land: ", response.json())
            return

        # print(f"Velocity: [{self.for_back_velocity}, {self.left_right_velocity}, {self.up_down_velocity}, {self.yaw_velocity}]")

        # Send Command to Backend
        query = {'relay_name': self.relay, 'drone_name': self.drone, 'cmd': [
            self.left_right_velocity, self.for_back_velocity, self.up_down_velocity, self.yaw_velocity]}
        print(query)
        response = requests.post(
            f'{BACKEND_URL}/drone/new_command', json=query, auth=self.HTTPAuthentication)
        print("CMD: ", response)

    def on_press(self, key) -> None:
        try:
            key_char = key.char.lower()
        except AttributeError:
            if key == keyboard.Key.space:
                key_char = 'space'
            elif key == keyboard.Key.shift:
                key_char = 'shift'
            else:
                return

        if key_char in self.key_mapping and key_char not in self.pressed_keys:
            if key_char != 't' or key_char != 'l':
                self.pressed_keys.add(key_char)
            self.update_velocity(key_char=key_char, mapping=self.key_mapping)

    def on_release(self, key) -> None:
        try:
            key_char = key.char.lower()
        except AttributeError:
            if key == keyboard.Key.space:
                key_char = 'space'
            elif key == keyboard.Key.shift:
                key_char = 'shift'
            else:
                return

        if key_char in self.key_mapping_release and key_char in self.pressed_keys:
            self.pressed_keys.remove(key_char)
            self.update_velocity(
                key_char=key_char, mapping=self.key_mapping_release)

        if key == keyboard.Key.esc:
            # Stop the listener
            return False


if __name__ == '__main__':
    controller = Controller(
        port=58899,
        relay_name='relay_0001',
        drone_name='drone_0001',
        HTTPAuthentication='hello'
    )
