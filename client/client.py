import threading
from http import HTTPStatus
from time import sleep

import requests
import PySimpleGUI as sg

from controller import Controller

from models.json_web_token.jwt_model import JWT
from models.http_bearer import HTTPBearer

from config import (
    BACKEND_IP,
    BACKEND_URL,
)

from logger_setup import log

sg.theme('SystemDefault1')
sg.SetOptions(
    font=('Arial Bold', 12)
)


class Client:
    def __init__(self) -> None:
        self.server_info = {}

        # Stores the object (class) which handles the direct drone connection
        self.controller: object = None
        self.video_port = None

        # NEW VAR BY Mikkel-Coder
        self.JWT: JWT | None
        self.authenticated: bool = False
        self.HTTPAuthorization: HTTPBearer
        self.active_relayboxes: list[str] = []
        # END NEW VARIABLES BY Mikel-Coder

        self.login_GUI()
        self.main()

    def main(self) -> None:
        layout = [
            [
                sg.Text('Select a device:')
            ],
            [
                sg.Combo(
                    [],
                    key='-ACTIVE_RELAYS-',
                    size=(20, 1),
                    readonly=True
                )
            ],
            [
                sg.Combo(
                    [],
                    key='-ACTIVE_DRONES-',
                    size=(20, 1),
                    readonly=True
                )
            ],
            [
                sg.Button(
                    button_text='Connect',
                    key='-CONNECT_DRONE-'
                ),
                sg.Button(
                    button_text='Disconnect',
                    key='-DISCONNECT_DRONE-',
                    disabled=True
                )
            ]
        ]

        self.device_window = sg.Window('Device List', layout, finalize=True)

        # Continuously get relaybox and Tello drone data from the backend.
        threading.Thread(
            name='InfoThread',
            target=self._information,
            daemon=True
        ).start()

        while True:
            event, values = self.device_window.Read()
            relay_name: str = self.device_window['-ACTIVE_RELAYS-'].get()
            drone_name: str = self.device_window['-ACTIVE_DRONES-'].get()

            if event == sg.WIN_CLOSED:
                try:
                    self.controller.process.kill()
                    log.debug('ffmpeg process killed')
                except AttributeError:
                    log.warning('ffmpeg process was never begun...')

                self.logout_GUI()

                # Kill the drone connection if on
                if self.controller:
                    self.controller.vidsock.close()
                    del self.controller
                    self.controller = None
                break

            if event == '-CONNECT_DRONE-':
                relay_name: str = self.device_window['-ACTIVE_RELAYS-'].get()
                drone_name: str = self.device_window['-ACTIVE_DRONES-'].get()

                if relay_name == '' and drone_name == '':
                    continue

                # Get specific drone from dict
                log.info(
                    f'Connecting to Relay: {relay_name} on Drone: {drone_name}'
                )

                # Verify with information from Backend
                connected_drone_info = self.server_info[relay_name][drone_name]

                # Update Buttons
                self.device_window['-CONNECT_DRONE-'].Update(disabled=True)
                self.device_window['-DISCONNECT_DRONE-'].Update(
                    disabled=False)

                # Identify Video Port
                self.video_port = int(connected_drone_info['port'])

                # Create Class
                self.controller: Controller = Controller(
                    port=self.video_port,
                    drone_name=drone_name,
                    relay_name=relay_name,
                    HTTPAuthentication=self.HTTPAuthorization
                )

            if event == '-DISCONNECT_DRONE-':
                # If the user has connected to a drone
                if not self.controller:
                    continue

                self.device_window['-CONNECT_DRONE-'].Update(
                    disabled=False)
                self.device_window['-DISCONNECT_DRONE-'].Update(
                    disabled=True)

                # Kill the Video Process
                try:
                    self.controller.process.kill()
                    log.debug('ffmpeg process killed')
                except:
                    log.warning('ffmpeg process was never begun...')

                # Delete the socket and object
                del self.controller
                self.controller = None

            if event == '-UPDATE_RELAYS-':
                self.device_window['-ACTIVE_RELAYS-'].Update(
                    values=values[event]
                )

            if event == '-UPDATE_DRONES-':
                self.device_window['-ACTIVE_DRONES-'].Update(
                    values=values[event]
                )

        self.device_window.close()

    def login_GUI(self) -> None:
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

        # Used to check if the drone pilot has pressed the 'Enter'
        # keyboard button.
        login_window['-USERNAME-'].bind("<Return>", "_Enter")
        login_window['-PASSWORD-'].bind("<Return>", "_Enter")

        # As long as the drone pilot has not been authenticated.
        while not self.authenticated:
            event, values = login_window.read()

            # If the drone pilot hits 'enter' or 'login' button.
            if event in ('Login', '-USERNAME-_Enter', '-PASSWORD-_Enter'):

                # Authenticate with the backend API.
                response = self.authenticate_API(
                    values['-USERNAME-'],
                    values['-PASSWORD-']
                )

                # If there was a critical error. For example no connection.
                if not isinstance(response, HTTPStatus):
                    log.critical(f'Failed to login with error: {response}')
                    sg.PopupError(response)
                    continue

                # If the response code was not okay.
                if not response == HTTPStatus.OK:
                    log.warning(
                        f'Failed to authenticate because of {response.name} {response.value}'
                    )
                    sg.PopupError(response.description, title=response.name)
                    continue

            # If we close the login window.
            if event == sg.WINDOW_CLOSED:
                login_window.close()
                exit()

        # When we have been authenticated, close the login window.
        login_window.close()

    def authenticate_API(self, username: str, password: str) -> HTTPStatus | Exception:
        """Authenticate to the backend.

        Authenticate a drone pilot at `/v1/api/frontend/login`
        with `username` and `password`

        Args:
            username (str): The username of the drone pilot.
            password (str): The associated password of the username.

        Returns:
            Exception (requests.exceptions.RequestException): 
            if the endpoint was not reachable.
            HTTPStatus: If a HTTP connection was made. Returns `OK`
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
                # Return the HTTPStatus code to the login GUI.
                return HTTPStatus(response.status_code)

            # Else, then are we authenticated
            # Now, retrieve the scheme and token.
            scheme, token = response.json().get('access_token').split()

            # Create and store the token as a JWT.
            self.JWT = JWT(token, scheme)

            # Create and store the `requests` authentication interface.
            # Se `requests` docs for more detail.
            self.HTTPAuthorization = HTTPBearer(self.JWT)

            # The drone pilot is now authenticated.
            self.authenticated = True

            return HTTPStatus.OK

        # If the post request was not able to reach the backend:
        # for example a timeout. Return the exception for the login GUI.
        except requests.exceptions.RequestException as exception:
            return exception

    def logout_GUI(self) -> None:
        """The main logout method.

        This method renders GUI confirming that the drone pilot has been
        logout successfully. 
        """
        # Deauthenticate with backend API.
        response = self.deauthenticated_API()

        # If the drone pilot was able to be deauthenticated.
        if response == HTTPStatus.OK:
            # Display a small window letting them know.
            sg.PopupNoButtons(
                'Succesful logoff. Goodbye!',
                auto_close=True,
                auto_close_duration=2,
                no_titlebar=True,
                keep_on_top=True,
            )
            # We can now exit.
            exit()

        # If the drone pilot was not able to be deauthentiacted.
        log.critical(f'Failed to logout with error: {response}')

        # Ask the drone pilot if they wish to try again.
        try_again: str = sg.PopupYesNo(
            f'Failed to logout with error: {response} \n Try again?',
            no_titlebar=True,
            keep_on_top=True
        )

        # If the want to try to logout again.
        if try_again == 'Yes':
            self.logout_GUI()

        # Else terminate.
        exit()

    def deauthenticated_API(self) -> HTTPStatus | Exception:
        """Deauthenticated the drone pilot.

        Deauthenticates the drone pilot at `/v1/api/frontend/logout`.

        Raises:
            RuntimeError: If the drone pilot has never been authenticated. 

        Returns:
            Exception (requests.exceptions.RequestException): 
            if the endpoint was not reachable.
            HTTPStatus: If a HTTP connection was made. Returns `OK`
            if authentication was successful. 

        Note:
            Se backend `/v1/api/frontend/logout for more detail about
            deauthentication.
        """
        if not self.authenticated:
            raise RuntimeError(
                'Cannot deauthenticated because the drone pilot has never been authenticated'
            )

        try:
            # Post to the ULR with authenticator.
            response = requests.post(
                f'{BACKEND_URL}/logout',
                auth=self.HTTPAuthorization
            )

            # If we where not able to be deauthenticate.
            if not response.ok:
                # Return the HTTPStatus to the logout GUI.
                return HTTPStatus(response.status_code)

            # Else, then we must be deauthenticated.
            # Delete JWT and authenticator.
            del self.JWT
            del self.HTTPAuthorization

            # The drone pilot is now deauthenticated.
            self.authenticated = False

            return HTTPStatus.OK

        # If the post request was not able to reach the backend API:
        # for example a timeout. Return the exception for the logout GUI.
        except requests.exceptions.RequestException as exception:
            return exception

    def _information(self) -> None:
        # Retrive data from backend about all relayboxes.
        # Store it in memory.
        # The main GUI then dicovers that there is now data to display
        # Displays it

        old_relays = []
        old_drones = []

        while self.authenticated:
            relay_list = []
            drone_list = []

            try:
                response = requests.get(
                    f'{BACKEND_URL}/relayboxes/all',
                    auth=self.HTTPAuthorization
                )
                self.server_info = response.json()

            except requests.exceptions.RequestException as exception:
                log.critical(
                    f'[{threading.current_thread().name}] {exception}'
                )

            try:
                # Update the Relay Combo
                for relay in self.server_info.keys():
                    relay_list.append(relay)

                if relay_list != old_relays:
                    old_relays = relay_list
                    self.device_window.write_event_value(
                        '-UPDATE_RELAYS-', relay_list)

                relay = self.device_window['-ACTIVE_RELAYS-'].get()

                if relay in relay_list:
                    for drone in self.server_info[relay]:
                        drone_list.append(drone)
                else:
                    drone_list = []

                if drone_list != old_drones:
                    old_drones = drone_list
                    self.device_window.write_event_value(
                        '-UPDATE_DRONES-', drone_list)

                sleep(0.6)

            except AttributeError:
                log.error(
                    'Error failed to update drone and or relay since the gui has been killed.'
                )
