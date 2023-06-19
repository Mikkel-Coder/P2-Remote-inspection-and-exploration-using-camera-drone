import subprocess
import socket
import threading
from time import sleep, time
import re
from http import HTTPStatus

import requests

from models.json_web_token.jwt_model import JWT
from models.http_bearer import HTTPBearer


from tello_edu_drone import TelloEDUDrone as Drone

from logger_config import log

from config import BACKEND_URL


class Relaybox:
    def __init__(self, name: str, password: str) -> None:
        """Creates a relaybox based on a name and a password.

        Arguments:
            name (str): The name of the relaybox.
            password (str): The password of the relaybox, used to access the backend. This should match an entry in mongoDB.
        """
        self.name: str = name
        self.password: str = password

        # Dict of drones currently connected to the relaybox
        self.drones: dict[Drone.name: dict[Drone.IP: id(Drone)]] = {}

        # Authorized drones on all relay boxes via the Tello EDU drones MAC addresses.
        self.AUTHORIZED_DRONES: list[str] = [
            '60-60-1f-5b-4b-ea',
            '60-60-1f-5b-4b-d8',
            '60-60-1f-5b-4b-78',
            '60-60-1f-5b-4c-15',
            '60-60-1f-5b-4a-0d'
        ]

        # A list for keeping track of all status ports that are in use.
        self.used_status_ports: list[int] = []

        # Socket for listing for possible reponses from the Tello drones. See their docs for more detail.
        self.response_socket: socket.socket = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM)
        self.response_socket.bind(('', 8889))

    def authenticate_API(self) -> None:
        credentials: dict = {
            'name': self.name,
            'password': self.password
        }

        try:
            # Post to the URL with the query.
            response = requests.post(
                f'{BACKEND_URL}/handshake',
                json=credentials
            )

            # If the credentials was not ok.
            if not response.ok:
                log.error(
                    f'Unable to be authenticated with code {response.status_code}'
                )

            # Else, then are we authenticated.
            # Now, retrieve the scheme and token.
            scheme, token = response.json().get('access_token').split()

            # Create and store the token as a JWT.
            self.JWT = JWT(token, scheme)

            # Create and store the `requests` authentication interface.
            # Se `requests` docs for more detail.
            self.HTTPAuthorization = HTTPBearer(self.JWT)

            # The drone pilot is now authenticated.
            self.authenticated = True

        except requests.exceptions.RequestException as exception:
            log.critical(
                f'Unable to connect to {BACKEND_URL} with exception: {exception}'
            )
            sleep(10)
            self.authenticate_API()

    def start(self) -> None:
        """Start scaning for drones and start heartbeat with backend

        Starts a thread that only checks for Tello Drones.
        It also starts a thread for heartbeat with backend.

        Notes:
            Call this after authentication with backend.
        """
        log.info("[THREAD] Scanning for drones...")

        threading.Thread(
            target=self.scan_for_drone,
            name='ScanForDronesThread'
        ).start()

        # Start a new thread with the heartbeat
        log.info("[THREAD] Starting heartbeat...")
        threading.Thread(
            target=self.heartbeat,
            name='HeartbeatThread'
        ).start()

    def heartbeat(self, interval: int = 3) -> None:
        """Maintain a connection with the backend.

        Maintains a connection for the relaybox so that is does not time out.
        This is used so that the backend knows the status of the relaybox.
        It also updates the backend with new information about its connected Tello drones
        """
        while True:
            try:
                query = {'name': self.name}
                response = requests.get(
                    f'{BACKEND_URL}/heartbeat',
                    auth=self.HTTPAuthorization,
                    timeout=10,
                    json=query
                ).json()

            except requests.exceptions.Timeout:
                log.error("Heartbeat timed out")
                continue

            except requests.exceptions.RequestException:
                log.critical("Heartbeat failed")
                continue

            # Check if backend data is up to date with the data the relay has
            log.info(
                f'Heartbeat | {self.name}: {self.drones.keys()}'
            )
            sleep(interval)

    def scan_for_drone(self) -> None:
        """
        Scans the local network for drones and filters out unauthorized and
        unresponsive drones. Adds authorized drones to the relay's list of drones.

        This method is used in a thread to constantly scann the 
        local network for Tello EDU Drones.

        Note:
            This has only been tested on Windows 10.
            Other OS has not been tested.

        Examples:
            Here a `arp -a` has been used with Microsoft CMD.

            >>> Interface: 192.168.1.101 --- 0xe
                    Internet Address      Physical Address      Type
                    192.168.1.1           ##-##-##-##-##-##     dynamic
                    192.168.1.255         ff-ff-ff-ff-ff-ff     static
                    224.0.0.22            01-00-5e-00-00-16     static
                    224.0.0.251           01-00-5e-00-00-fb     static
                    224.0.0.252           01-00-5e-00-00-fc     static
                    239.255.255.250       01-00-5e-7f-ff-fa     static
                    255.255.255.255       ff-ff-ff-ff-ff-ff     static

            A example of the `ping -w 100 -n 4 127.0.0.1`

            >>> Pinging 127.0.0.1 with 32 bytes of data:
                    Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
                    Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
                    Reply from 127.0.0.1: bytes=32 time<1ms TTL=128
                    Reply from 127.0.0.1: bytes=32 time<1ms TTL=128

                    Ping statistics for 127.0.0.1:
                        Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
                    Approximate round trip times in milli-seconds:
                        Minimum = 0ms, Maximum = 0ms, Average = 0ms
        """
        while True:
            # The First 3 numbers in the IPv4 does not change on Windows when HotSpot is active.
            # The last part of the regex is to find the MAC. NOTE: that on windows `-` are used to separate in the MAC.
            # The ´type´ is not important.
            regex = r"""(192\.168\.137\.[0-9]{0,3}) *([0-9a-z-]*)"""

            # Run CMD command `arp -a`, to get all current connections.
            output: str = str(subprocess.check_output(['arp', '-a']))
            output = output.replace(" \r", "")
            scanned_drones: list[tuple(str, str)] = re.findall(
                regex, output)  # [(192.168.137.xxx, 00:00:00:00:00:00), ...]

            # Filter out unauthorized drones as drone[1] by comparing their MAC addresses with the AUTHORIZED_DRONES list.
            for drone in scanned_drones[:]:
                if drone[1] not in self.AUTHORIZED_DRONES:
                    scanned_drones.remove(drone)

            # Loop through all authorized drones with `ping`, where `-w` is the maximum response time, `-n` is the amount of pings, `drone[0]` is the IP of the Tello drone.
            for drone in scanned_drones[:]:
                cmd: str = f"ping -w 100 -n 4 {drone[0]}"
                pinging = str(subprocess.run(cmd, capture_output=True))
                pinging = pinging.replace(" \r", "")

                # If no ping (ICMP) was successful remove the drone, since it must not be on the network anymore.
                if "Received = 0" in pinging:
                    scanned_drones.remove(drone)

            self.filter_scanned_drones(scanned_drones)

    def filter_scanned_drones(self, scanned_drones: list) -> None:
        """
        Filters the list of scanned drones and adds new drones to the relay's list of drones, or removes disconnected drones.

        Arguments:
            scanned_drones (list): A list of tuples containing the IP addresses and MAC addresses of the scanned drones.
        """
        # Check for connected drone
        for drone in scanned_drones:
            # Create a list of IP addresses of currently connected drones.
            IPs_mapped: list = []

            for name in self.drones:
                IPs_mapped.append(self.drones[name].get('IP'))

            # If the scanned drone is not in the list of connected drones, add it to the relay's list of drones with the add_drone()
            if drone[0] not in IPs_mapped:
                log.info(f"[CONNECTED] {drone}")
                self.add_drone(drone[0])

        # Append the connected drone to a list containing all object ids of the drones.
        drones_object_list: list[dict[str: (str, id(Drone))]] = []
        for name in self.drones:
            drones_object_list.append(self.drones[name].get('objectId'))

        for drone in drones_object_list:
            # resest the list of IP addresses of currently scanned drones
            IPs_mapped: list = []

            for drone_IP in scanned_drones:
                IPs_mapped.append(drone_IP[0])

            # If the IP address of the drone is not in the list of scanned drones, remove it from the relay's list of drones
            if drone.host_IP not in IPs_mapped:
                log.info(f"[DISCONNECTED] {drone.name} {drone.host_IP}")
                self.delete_drone(drone.name)
                self.disconnected_drone(drone)

    def add_drone(self, host_IP: str) -> None:
        """
        Adds a new drone to the RelayBox's list of active drones.

        This method creates a new Drone object, generates a unique name for it based on the IP address, 
        and starts a new thread to handle the drone's communication. The new drone is added to the RelayBox's 
        list of active drones with its IP address and object ID.

        Arguments:
            host_IP (str): The IP address of the drone to be added.
        """
        # Find a unique name for the drone
        used_names = []

        # Add connected drone's name to a list with used_names so we do not get duplicates
        for drone in self.drones.keys():
            used_names.append(drone)

        # Since tello utilizes the last 8 bits of the IP header, we can have a total of 254 IPs, excluding the router's own.
        for num in range(1, 254):
            if "drone_{:03d}".format(num) not in used_names:
                drone_name = "drone_{:03d}".format(num)
                break
        else:
            raise ValueError('No Available names for new drone')

        # Get a status port for the specfic drone
        status_port = self.get_status_port()

        # create a new drone object now
        drone = Drone(
            name=drone_name,
            parent=self.name,
            host_IP=host_IP,
            status_port=status_port,
            response_socket=self.response_socket
        )

        # Append the new created drone to the relayboxs list of active drones.
        self.drones[drone_name]: dict = {"IP": host_IP, "objectId": drone}

        # Create a new thread for the added drone to communicate to it.
        threading.Thread(
            target=drone.start,
            name='DroneThread'
        ).start()

    def delete_drone(self, name: str) -> None:
        """Delete a drone, that is no longer connected to the relaybox.

        Arguments:
            name (str): The name of the drone, like `drone_001`
        """
        # Get the object id from the name, by looking in the self.drone dictionary.
        object: Drone = self.drones[name].get('objectId')

        # Remove the status port so it can be re-used.
        self.used_status_ports.remove(object.status_port)

        # Set to False to end the threads: video, status, rc and land. This has to be done before closing the sockets to avoid a socket error.
        object.drone_active: bool = False

        # Close the status and video socket to allow a new drone to use it.
        object.status_socket.close()
        object.video_socket.close()

        # Delete the drone object from memory
        del object

        # Now remove it from the relays list of active drones.
        self.drones.pop(name)

    def disconnected_drone(self, drone: object) -> None:
        """Update the backend, that a drone has been disconnted from the local network.

        Arguments:
            drone (Drone): A drone object.
        """
        # Post to the backend endpoint to tell it that the drone have disconnected.
        query = {'name': drone.name, 'parent': drone.parent}
        response = requests.post(
            f'{BACKEND_URL}/drone/disconnected',
            json=query
        )

        # If the responescode was not OK.
        if not response.ok:
            # Try again
            log.error(
                f'Error: {response.url} | {response.status_code} | Retrying in 2 seconds')
            sleep(2)
            self.disconnected_drone(drone)

    def get_status_port(self) -> int:
        """Get an available status port for the drone.

        Notes:
            The status is a part of the Tello EDU drone. See thier docs for more detail.
        """
        # All 254 usable drone status ports, since the range is from 50400 to 50655, but not including it, which equals a total of 254 ports.
        for status_port in range(50400, 50655):

            # Raise exception if the maximum amount of status ports have been used.
            if len(self.used_status_ports) >= 254:
                raise ValueError('No available control ports')

            # if the port is not yet used, use it.
            if status_port not in self.used_status_ports:

                # Append port to used_status_ports to keep track of which ports are in use.
                self.used_status_ports.append(status_port)

                # Return the port that should be used to receive status from the drone.
                return status_port
