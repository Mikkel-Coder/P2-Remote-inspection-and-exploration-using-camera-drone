import socket
import threading
from time import sleep

from config import BACKEND_URL

import requests
from logger_config import log


class TelloEDUDrone:
    """A model of a Tello drone

    The purpose of this class to to have a interface for a relay to talk to. 
    It is like the offcial Tello EDU API, but does not share any codebase.

    Reference:
        [0] [Tello EDU Docs]   
    """

    def __init__(
        self,
        name: str,
        parent: str,
        host_IP: str,
        status_port: int,
        response_socket: socket.socket
    ) -> None:
        """Creates a drone based on a name, a parrent (relaybox), host_IP, status_port and a socket.

        Arguments:
            name (str): The name of the drone.
            parent (str): The name of the relaybox.
            host_IP (str): The IP of the drone.
            status_port (int): The port that the drone should send status messages to.
            response_socket (socket.socket): A socket for receiving a response when a command have been sent.
        """
        self.name: str = name
        self.host_IP: str = host_IP
        self.video_port: int | None = None
        self.status_port: int = status_port

        # The relaybox that the drone belongs to.
        self.parent: str = parent

        # The IPv4 address for the backend.
        self.backend_IP = '00.00.00.00'  # TODO: This could be an URL instead

        # A UDP socket for receiving the video feed from the drone.
        self.video_socket: socket.socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM)
        self.buffer_size: int = 2048

        # Socket for checking that multiple drones received commands before changing its ports.
        self.response_socket: socket.socket = response_socket

        # Set timeout for response socket in seconds
        self.response_socket.settimeout(1)

        # A UDP socket for receiving status from drone.
        self.status_socket: socket.socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM)  # IPv4 UDP
        self.status_socket.bind(('', self.status_port))

        # Flags for the drone's state.
        self.drone_active: bool = True
        self.takeoff: bool = False

        self.query = {'name': self.name, 'parent': self.parent}

    def start(self) -> None:
        """Starts the necesary logic for the drone to connect to the backend and a client.

        Starts mutliple threads that get a video feed, drone status, if the drone should land and the commands it should perform.
        It also starts a thread for heartbeat with backend.

        Note:
            The many if statments are there to not go through code after the drone have diconnected, 
            since this happens in another thread in the Relaybox class.
            This method is called after `add_drone()` in the Relaybox
        """
        log.info(
            f'Starting [{self.name} at {self.host_IP}] on {self.parent}'
        )
        log.debug(
            f'[{self.name}] Getting available video ports from backend...'
        )
        self.get_video_port()
        log.debug(f'Got port: {self.video_port}')
        log.debug(f'[{self.name}] Entering SDK mode...')
        self.send_control_command('command')
        log.debug(f'[{self.name}] Entered SDK mode')

        # Wait 1 seconds for the SDK mode to start. (Tello limitation)
        sleep(1)

        if self.drone_active:
            log.debug(
                f'[{self.name}] Telling drone to use port {self.video_port} for streamon...')
            self.set_drone_ports()
            log.debug(
                f"{self.name} used {self.video_port} port for streamon")

        # Ready To Stream (RTS) handshake with backend
        if self.drone_active:
            log.debug(
                f"[{self.name}] Sending Handshake Packet to Backend and awaiting response...")
            self.RTS_handshake()

        # Wait 1 seconds for the ports to be correctly set. (Tello limitation)
        sleep(1)

        # Now that we have a status and video port, begin to stream
        self.send_control_command("streamon")

        # Set the speed of the Tello, the default value is rather low, so we set it higher
        # NOTE: See Tello EDU docs about speed interval.
        self.send_control_command("speed 60")

        if self.drone_active:
            # Start Threads for each process
            log.debug(f"[{self.name}]: Starting the 4 required threads.")

            threading.Thread(
                name='VideoThread',
                target=self.video_thread
            ).start()

            threading.Thread(
                target=self.status_thread,
                name='StatusThread'
            ).start()

            threading.Thread(
                target=self.rc_thread,
                name='RemoteControlThread'
            ).start()

            threading.Thread(
                target=self.landing_thread,
                name='LandingThread'
            ).start()

            log.debug(f"[{self.name}]: All threads have started.")

    def status_thread(self) -> None:
        """A Thread for handling the drone's status

        This method runs on a separate thread and listens for status updates from the drone.
        When it receives a status update, it sends the information to the backend.
        """
        # Continuously listen for status updates while the drone is active.
        while self.drone_active:

            # Receive the status update and the address it came from.
            status, addr = self.status_socket.recvfrom(self.buffer_size)

            # We do not want to spam the backend, therefore we wait 100ms.
            sleep(0.1)

            # Post the status to a backend endpoint.
            query = {
                'name': self.name,
                'parent': self.parent,
                'status_information': status.decode('utf-8')
            }

            requests.post(
                f'{BACKEND_URL}/drone/status_information', json=query)

    def landing_thread(self) -> None:
        """Check if the drone should land.

        Continuously checks with the backend server to see if the drone 
        should land. 
        """
        # Continuously listen for status updates while the drone is active.
        while self.drone_active:
            should_land = requests.get(
                f'{BACKEND_URL}/drone/should_land', json=self.query)
            sleep(0.1)

            # If the backend indicates that the drone should land
            if '<Response [200]>' == str(should_land):
                self.takeoff = False
                self.send_control_command('land')

                status_message = requests.post(
                    f'{BACKEND_URL}/drone/successful_land', json=self.query
                )

                log.debug(
                    f'{self.name} succesfully landed with status: {status_message}'
                )

    def rc_thread(self) -> None:
        """Sends commands to the drone received from the backend.

        Continuously checks with the backend server to see if it should land
        and updates its commands for controlling the drone.

        """
        self.takeoff: bool = False

        while self.drone_active and (not self.takeoff):
            # Sleep so that we do not spam the backend server.
            sleep(1)

            # Try to check it the drone should takeoff
            try:
                response = requests.get(
                    f'{BACKEND_URL}/drone/should_takeoff',
                    json=self.query
                )
                log.debug(f'{response}')

            # If it fails to do so
            except requests.exceptions.RequestException as exception:
                # Wait and repeat.
                log.critical(
                    f'[{threading.current_thread().name}] {exception}')
                sleep(2)
                self.rc_thread()

            # If the response was successful.
            if response.ok:
                # The drone should now takeoff
                self.send_control_command('takeoff', recv_timeout=7)
                log.debug(
                    f'Completed takeoff for {self.name} at {self.parent}')

                # Update the takeoff flag.
                self.takeoff = True

                # Update the backend statues of the drone about the takeoff.
                response = requests.post(
                    f'{BACKEND_URL}/drone/successful_takeoff', json=self.query)

            # Now we check for controls from the backend.

            # The reason for having the same while loop is because the drone
            # may become inactive. The while loop is to more quickly return if a drone is diconnected.
            # This saves a small amount of resource.

            while self.drone_active and self.takeoff:
                # Get commands from the backend endpoint: cmd_queue.
                commands = requests.get(
                    f'{BACKEND_URL}/cmd_queue',
                    json=self.query
                ).json().get('message')

                # Create a string that we can pass directly to the drone.
                drone_command = f'rc {commands[0]} {commands[1]} {commands[2]} {commands[3]}'

                # Send the received command to the Tello drone.
                self.send_rc_command(drone_command)

                # # Get commands from the backend endpoint: cmd_queue.
                # response = requests.get(
                #     f'{BACKEND_URL}/cmd_queue',
                #     json=self.query
                # )

                # commands: dict = response.json()

                # # { 'message': [1, 2, 3, 4]}
                # commands: dict = commands.get('message')

                # # Create a string that we can pass directly to the drone.
                # drone_command = f'rc {commands[0]} {commands[1]} {commands[2]} {commands[3]}'

                # # Send the received command to the Tello drone.
                # self.send_rc_command(drone_command)

    def RTS_handshake(self) -> None:
        """Perform a handshake with the backend to establish a drone's readiness to send video.

        Sends an Ready To Stream message to the backend to indicate that the drone is ready to stream video.
        """

        self.video_socket.settimeout(2)

        while self.drone_active:
            # RTS = Ready To Stream
            try:
                # Send an RTS message to the backend to indicate that the drone is ready to stream video.
                self.video_socket.sendto(
                    b'RTS', (self.backend_IP, self.video_port)
                )
                log.debug('Send an RTS message')
            except OSError as error:
                log.debug(f'{error}, socket have already been closed.')

            try:
                # We are only receving a flag, so a buffer of 32 is more than sufficient.
                data, addr = self.video_socket.recvfrom(32)

                # If we get permission from the backend.
                if data:
                    log.debug('Received RTS message')
                    break
                else:
                    log.debug(
                        'Did not receive confirmation of RTS, resending in 2sec ...')
                    sleep(2)

            except:
                log.error('Error receiving confirmation from backend')
                sleep(2)

        if self.drone_active:
            log.debug(f'Completed handshake for {addr}')

    def video_thread(self) -> None:
        """Send video from the drone to the backend.

        A thread for streaming video feed from the drone to the backend.

        This method continuously receives video feed from the drone over a socket connection and sends it to the backend
        over the same socket connection. The specific video feed port to use is obtained from the backend by calling
        get_video_port(). The function runs until self.drone_active is set to False.
        """
        while self.drone_active:
            try:
                # Retrive the video feed from the Tello drone
                video_feed, addr = self.video_socket.recvfrom(self.buffer_size)

            except Exception:
                log.error(f'Socket have already been closed: {addr}')

            try:
                # Now send that video to the backend
                self.video_socket.sendto(
                    video_feed, (self.backend_IP, self.video_port))

            except Exception:
                log.error(f'Socket have already been closed: {addr}')

    def get_video_port(self) -> None:
        """Gets a video port from the backend
        """
        response = requests.get(f'{BACKEND_URL}/new_drone', json=self.query)

        if not response.ok:
            log.error(
                f"Failed trying to get available port from URL [{response.url}] with status code {response.status_code}")

            # If we did not get a video port.
            if self.drone_active:
                # try again.
                sleep(2)
                self.get_video_port()

        # Update the drones video port.
        port: int = response.json().get('video_port')
        self.video_port = port

    def set_drone_ports(self) -> None:
        """Set drone status and video ports.

        Send a command to the drone to configure its status_port and video_port.        
        """
        # Bind the video_socket to the given video port, given by the backend server.
        self.video_socket.bind(('', self.video_port))

        # Send a SDK command to tell the Tello drone to change its status and video feed ports.
        self.send_control_command(f"port {self.status_port} {self.video_port}")

    def send_control_command(self, command: str, recv_timeout: int = 1) -> bool | None:
        """Send a command to the drone with reurn.

        Arguments:
            command (str): The command to send to the drone.

        Example:
            >>> send_control_command('speed 60')
            True

        Notes:
            The command must be of same format as the Tello EDU Drone.
            Se Tello EDU docs for more detail.

        """
        try:
            self.response_socket.settimeout(recv_timeout)
        except Exception as error:
            log.error(f'Error setting timeout {recv_timeout}')

        # Try everything because the drone may disconnect without notifying us.
        try:
            # As long the drone is active.
            while self.drone_active:

                # Define `response` and `addr` for error handling
                response = None
                addr = None

                try:
                    # Send command and await response.
                    log.debug(
                        f'Sending command: {command} to {self.name} at {self.host_IP} and awaiting response.')

                    # Send the command to the drone.
                    self.response_socket.sendto(
                        # Default formatring for the Tello drone
                        bytes(command, 'utf-8'),
                        # The default command port for the Tello EDU drone
                        (self.host_IP, 8889)
                    )

                    # Await its response.
                    response, addr = self.response_socket.recvfrom(
                        self.buffer_size)

                # The OS may not be able to send via the socket at that moment, so we log.
                except OSError:
                    log.debug(
                        f'Error did not receive response from {self.name} at {self.host_IP}, resending new command: {command} in 2s.')
                    sleep(2)

                # If we get a response from the drone.
                if response != None:
                    log.debug(
                        f'Received response: {response} from {self.name} at {self.host_IP}')
                    decoded_response = response.decode('utf-8')

                    # Check if we receive and 'ok' and its on the right IP.
                    if ('ok' == decoded_response) and (addr[0] == self.host_IP):
                        log.debug(f'{self.name}, returned ok')
                        return True

                # Otherwise the response was not received in time.
                log.debug('No response was received in the given time.')

            # In the case the we try to send a command to a drone, that is not active.
            if not self.drone_active:
                log.debug('Connection to drone lost.')

        # Log every error.
        except Exception as error:
            log.error(f'Error: {error}')

    def send_rc_command(self, command: str) -> None:
        """Send a command without a respones

        Arguments:
            command (str): A command to send to the drone.

        Notes:
            The command must be of same format as the Tello EDU Drone.
            Se Tello EDU docs for more detail.
        """
        try:
            # Send command and await response.
            log.debug(
                f'Sending command: {command} to {self.name} at {self.host_IP}.')

            # Send the command to the drone.
            self.response_socket.sendto(
                bytes(command, 'utf-8'), (self.host_IP, 8889))

        except OSError as error:
            log.error(f'{error}, socket have already been closed.')
