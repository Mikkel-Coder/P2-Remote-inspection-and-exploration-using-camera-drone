'''Config a rest Tello EDU drone to connect to a Relaybox'''

import socket


def config_TELLO_EDU(
    SSID: str = 'fakeRelay',
    password: str = 'WORDPASS',
    Tello_EDU_IPv4: str = '192.168.10.1'
) -> None:
    """Config a Tello EDU drone to enter SDK mode and connect to a Wireless
    Access Point (WAP).

    When the drone has been factory reset, configure it so, that it is capable
    to access a wireless access point and retrieve SDK commands.

    Args:
        SSID (str, optional): The name of the WAP. Defaults to "fakeRelay".
        password (str, optional): The WAP2 password. Defaults to "WORDPASS".
        Tello_EDU_IP (str, optional): The IPv4 address to the Tello EDU drone.
        Defaults to '192.168.10.1'.
    """

    # The default port for the Tello EDU drone to retrieve commands
    TELLO_EDU_PORT: int = 8889
    TELLO_EDU_ADDRESS: tuple = (Tello_EDU_IPv4, TELLO_EDU_PORT)

    # Create UDP socket to communicate to the Tello EDU drone.
    connection_UDP = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    connection_UDP.connect(TELLO_EDU_ADDRESS)

    # Initialize the Tello SKD.
    connection_UDP.send(b'command')
    print('Starting the SDK...')
    Tello_EDU_status_message = connection_UDP.recvfrom(128)
    print(Tello_EDU_status_message)

    # Config to WAP with password (WPA2)
    config_WiFi = bytes(f'ap {SSID} {password}', encoding='utf-8')
    connection_UDP.send(config_WiFi)
    print('Set to access point mode...')
    Tello_EDU_status_message = connection_UDP.recvfrom(128)
    print(Tello_EDU_status_message)


if __name__ == '__main__':
    config_TELLO_EDU()
