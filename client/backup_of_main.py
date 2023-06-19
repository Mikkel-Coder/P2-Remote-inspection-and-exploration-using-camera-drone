import subprocess
import requests
import socket
import threading
from time import sleep


from http import HTTPStatus



from models.json_web_token.jwt_model import JWT
from models.http_bearer import HTTPBearer

import PySimpleGUI as sg
from pynput import keyboard


import logging


logging.basicConfig(
    # Set the desired log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    # filename='app.log',  # Specify the log file name
    # filemode='w'  # Choose the file mode (e.g., 'w' for write mode, 'a' for append mode)
)

logger = logging.getLogger(__name__)


BACKEND_IP = 'localhost'
BACKEND_URL = f'http://{BACKEND_IP}:8000/v1/api/frontend'


class Client:
    def __init__(self,) -> None:
        self.server_info = {}
        self.active_relays = []
        self.active_drones = []

        # Stores the object (class) which handles the direct drone connection
        self.connection: object = None

        self.kill_trigger = threading.Event()

        self.username = 'admin'
        self.password = '123'
        self.token = None
        self.header = {'Authorization': f'Bearer {self.token}'}

        self.video_port = None

        # NEW VAR BY Mikkel-Coder
        self.JWT: JWT | None = None
        self.authenticated: bool = False
        self.HTTPAuthn: HTTPBearer

        self.login()
        self.main()

    def main(self):

        # Create GUI
        layout = [
            [sg.Text('Select a device:')],
            [sg.Combo([], key='-combo.active_relays-',
                      size=(20, 1), readonly=True)],
            [sg.Combo([], key='-combo.active_drones-',
                      size=(20, 1), readonly=True)],
            [sg.Button(button_text='Connect', key='-button.connect_drone-'), sg.Button(
                button_text='Disconnect', key='-button.disconnect_drone-', disabled=True)],
            [sg.Button(button_text='Exit Program',
                       key='-button.exit_program-')],
        ]

        self.window = sg.Window('Device List', layout, finalize=True)

        # Continuously Get Relay And Drone Info from Backend
        info_thread = threading.Thread(
            name='info_thread', target=self.information, args=())
        info_thread.start()

        while True:
            event, values = self.window.Read()

            if event in (sg.WIN_CLOSED, '-button.exit_program-'):
                try:
                    self.connection.process.kill()
                    print('ffmpeg process killed')
                except:
                    print('ffmpeg process was never begun...')

                # Kill the information gathering thread
                self.kill_trigger.set()

                self.logout()

                # Kill the drone connection if on
                if self.connection:
                    self.connection.vidsock.close()
                    del self.connection
                    self.connection = None
                break

            if event == '-button.connect_drone-':

                if (self.window['-combo.active_relays-'].get() != '') and (self.window['-combo.active_drones-'].get() != ''):

                    # Get specific drone from dict
                    relay_name = self.window['-combo.active_relays-'].get()
                    drone_name = self.window['-combo.active_drones-'].get()
                    print(
                        f"Connecting to Relay: {relay_name} on Drone: {drone_name}")

                    # Verify with information from Backend
                    connected_drone_info = self.server_info[self.window['-combo.active_relays-'].get(
                    )][self.window['-combo.active_drones-'].get()]

                    # Update Buttons
                    self.window['-button.connect_drone-'].Update(disabled=True)
                    self.window['-button.disconnect_drone-'].Update(
                        disabled=False)

                    # Identify Video Port
                    self.video_port = int(connected_drone_info['port'])

                    # Create Class
                    self.connection = controller(
                        port=self.video_port, drone_name=drone_name, relay_name=relay_name, security_header=self.header)

            if event == '-button.disconnect_drone-':
                # If the user has connected to a drone
                if self.connection:
                    self.window['-button.connect_drone-'].Update(
                        disabled=False)
                    self.window['-button.disconnect_drone-'].Update(
                        disabled=True)

                    # Kill the Video Process
                    try:
                        self.connection.process.kill()
                        print('ffmpeg process killed')
                    except:
                        print('ffmpeg process was never begun...')

                    # Delete the socket and object
                    del self.connection
                    self.connection = None

            if event == '-UPDATE_RELAYS-':
                self.window['-combo.active_relays-'].Update(
                    values=values[event])

            if event == '-UPDATE_DRONES-':
                self.window['-combo.active_drones-'].Update(
                    values=values[event])

        self.window.close()

    def login(self) -> None:
        """The main login method.

        This method creates a login GUI for the drone pilot to login via.
        """

        # The main layout of the login GUI.
        login_GUI = [
            [
                sg.Text('Username', size=(10, 1)),
                sg.Input(
                    key='-USERNAME-',
                    tooltip='Inter your username',
                    size=(20, 1)
                )
            ],
            [
                sg.Text('Password', size=(10, 1)),
                sg.Input(
                    key='-PASSWORD-',
                    password_char='*',
                    tooltip='Inter your password',
                    size=(20, 1),
                )
            ],
            [sg.Button('Login')]
        ]

        # Create the login window.
        login_window = sg.Window(
            title=f'Login to {BACKEND_IP}',
            layout=login_GUI,
            finalize=True
        )

        # Used to check if the drone pilot has pressed the 'Enter' keyboard button.
        login_window['-USERNAME-'].bind("<Return>", "_Enter")
        login_window['-PASSWORD-'].bind("<Return>", "_Enter")

        # As long as the drone pilot has not been authenticated.
        while not self.authenticated:
            event, values = login_window.read()

            # If the drone pilot hits 'enter' or 'login' button.
            if event in ('Login', '-USERNAME-_Enter', '-PASSWORD-_Enter'):

                # Authenticate with the backend.
                response = self.authenticate(
                    values['-USERNAME-'],
                    values['-PASSWORD-']
                )

                # If there was a critical error. For example no connection.
                if not isinstance(response, HTTPStatus):
                    logger.critical(response)
                    sg.PopupError(response)
                    continue

                # If the response code was not okay.
                if response != HTTPStatus.OK:
                    logger.warning(response.description)
                    sg.PopupError(response.description, title=response.value)
                    continue

            # If we close the login window.
            if event == sg.WINDOW_CLOSED:
                login_window.close()
                exit()

        # When we have been authenticated, close the login window.
        login_window.close()

    def authenticate(self, username: str, password: str) -> HTTPStatus | Exception:
        """Authenticate to the backend.

        Authenticate a drone pilot at `/v1/api/frontend/login`
        with `username` and `password`

        Args:
            username (str): The username of the drone pilot.
            password (str): The associated password of the username.

        Returns:
            Exception (requests.exceptions.RequestException): 
            if the endpoint was not reachable.
            HTTPStatus: If a http connection was made. Returns `OK`
            if authentication was successful. 
        
        Note:
            Se backend `/v1/api/frontend/login` for more detail about
            authentication.
        """
        # The excepted query for the URL.
        query = {
            'name': username,
            'password': password
        }

        try:
            # Post to the ULR with the query. 
            response = requests.post(f'{BACKEND_URL}/login', json=query)

            # If we where not able to be authenticated.
            if not response.ok:
                # Return the HTTPStatus to the login GUI.
                return HTTPStatus(response.status_code)

            # Else, then are we authenticated
            # Retrieve the token.
            token: str = response.json().get('access_token')

            # Create and store the token as a JWT.
            self.JWT = JWT(token)

            # Create and store the `requests` authentication interface.
            # Se `requests` docs for more detail.
            self.HTTPAuthn = HTTPBearer(self.JWT)

            # The drone pilot is now authenticated.
            self.authenticated = True

            return HTTPStatus.OK

        # If the post request was not able to reach the backend:
        # for example a timeout. Return the exception for the login GUI.
        except requests.exceptions.RequestException as exception:
            return exception

    def logout(self):
        response = requests.post(f'{BACKEND_URL}/logout', headers=self.header)
        print(f"{response.json()}")

    def information(self):

        old_relays = []
        old_drones = []

        while not self.kill_trigger.is_set():
            relay_list = []
            drone_list = []
            try:
                response = requests.get(
                    f'{BACKEND_URL}/relayboxes/all', headers=self.header)
                self.server_info = response.json()

            except Exception as e:
                print(f'{e}: Could not retrieve Relay and Drone Data')

            try:
                # Update the Relay Combo
                for relay in self.server_info.keys():
                    relay_list.append(relay)

                if relay_list != old_relays:
                    old_relays = relay_list
                    self.window.write_event_value(
                        '-UPDATE_RELAYS-', relay_list)

                relay = self.window['-combo.active_relays-'].get()

                if relay in relay_list:
                    for drone in self.server_info[relay]:
                        drone_list.append(drone)
                else:
                    drone_list = []

                if drone_list != old_drones:
                    old_drones = drone_list
                    self.window.write_event_value(
                        '-UPDATE_DRONES-', drone_list)

                # -----# Pass Status Information if Connected To Drone #-----#
                if self.connection != None:
                    # We Use copy to avoid iterating a changing list or performing simultaneous action on the same dictionary
                    # self.connection.status = copy.deepcopy(self.server_info[self.connection.relay][self.connection.drone]['status_information'])
                    try:
                        print("\nStatus Information: ",
                              self.server_info[self.connection.relay][self.connection.drone]['status_information'])
                    except:
                        print("No Drone Connected!")

                sleep(0.6)

            except AttributeError as tk:
                print(
                    'Error failed to update drone and or relay since the gui has been killed.')

        print('finished loop')


class controller:
    def __init__(self, port, relay_name, drone_name, security_header):

        # -----# Initialize Variables #-----#
        self.header = security_header
        self.relay = relay_name
        self.drone = drone_name
        self.port = port
        self.address = ('', 6969)  # Localhost
        self.backend_address = (BACKEND_IP, self.port)

        self.status = None  # Will be a string when updated

        self.vidsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.vidsock.bind(self.address)
        self.vidsock.settimeout(3)

        self.ffmpeg_cmd = ['C:/Users/chris/Documents/Comtek/ffmpeg-master-latest-win64-gpl/bin/ffplay',
                           '-i', f'udp://0.0.0.0:6969',
                           '-probesize', '32',
                           '-framerate', '30',
                           '-fflags', 'nobuffer',
                           '-flags', 'low_delay',
                           '-framedrop',
                           '-strict', 'experimental',
                           '-loglevel', 'panic']

        # -----# Controller/Key Mapping Variables #-----#

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

        # -----# Start the Object Handler #-----#
        handle_thread = threading.Thread(target=self.handle, args=())
        handle_thread.start()

    def handle(self):
        verified = False
        count = 0
        data = None

        # Await Backend Verification
        while verified == False:
            try:
                self.vidsock.sendto('rts'.encode('utf-8'),
                                    self.backend_address)
            except Exception as e:
                print(f'Could not send RTS: {e}')

            try:
                data, backend = self.vidsock.recvfrom(2048)

            except Exception as e:
                count += 1
                print(f"Socket Error: {e} \nRetrying RTS")

            if count == 10:
                # If on 10th retry
                print("Could Not Verify With Backend")
                return

            if data:
                print("Verification Complete")
                verified = True

        # Close the socket to allow use from FFMPEG.
        self.vidsock.close()

        # Start the Video Process
        video_thread = threading.Thread(
            name='video_stream', target=self.video, args=())
        video_thread.start()

        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

    def video(self):
        print("Starting Video Process")
        self.process = subprocess.Popen(
            self.ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def update_velocity(self, key_char, mapping):
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
            # Takeoff
            query = {'name': self.drone, 'parent': self.relay}
            response = requests.post(
                f'{BACKEND_URL}/drone/takeoff', json=query, headers=self.header)
            print("Takeoff: ", response.json())
            return

        elif key_char == 'l':
            # Land
            query = {'name': self.drone, 'parent': self.relay}
            response = requests.post(
                f'{BACKEND_URL}/drone/land', json=query, headers=self.header)
            print("Land: ", response.json())
            return

        # print(f"Velocity: [{self.for_back_velocity}, {self.left_right_velocity}, {self.up_down_velocity}, {self.yaw_velocity}]")

        # Send Command to Backend
        query = {'relay_name': self.relay, 'drone_name': self.drone, 'cmd': [
            self.left_right_velocity, self.for_back_velocity, self.up_down_velocity, self.yaw_velocity]}
        print(query)
        response = requests.post(
            f'{BACKEND_URL}/drone/new_command', json=query, headers=self.header)
        print("CMD: ", response)

    def on_press(self, key):
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

    def on_release(self, key):
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
    control = Client()
