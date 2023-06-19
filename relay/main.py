from relaybox import Relaybox

relay = Relaybox("relay_0001", "123")
relay.authenticate_API()
# relay.backend_authentication()
relay.start()
