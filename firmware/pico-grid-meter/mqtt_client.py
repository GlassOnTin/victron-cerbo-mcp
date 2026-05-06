"""MQTT publisher with TLS and reconnect.

Uses umqtt.simple from micropython-lib. The Cerbo's broker (dbus-flashmq)
presents a self-signed cert; we connect with cert verification disabled
since traffic stays on the LAN.
"""

import ssl
import time

from umqtt.simple import MQTTClient


class MqttPublisher:
    def __init__(
        self,
        client_id: str,
        host: str,
        port: int,
        username,
        password,
        use_tls: bool,
        tls_insecure: bool,
        keepalive_s: int,
    ):
        self._client_id = client_id
        self._host = host
        self._port = port
        self._user = username
        self._pw = password
        self._keepalive = keepalive_s
        self._client = None

        if use_tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if tls_insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx
        else:
            self._ssl_ctx = None

    def _new_client(self) -> MQTTClient:
        return MQTTClient(
            client_id=self._client_id,
            server=self._host,
            port=self._port,
            user=self._user,
            password=self._pw,
            keepalive=self._keepalive,
            ssl=self._ssl_ctx,
        )

    def connect(self) -> bool:
        self._client = self._new_client()
        try:
            self._client.connect()
            return True
        except Exception as e:
            print("[mqtt] connect failed:", e)
            self._client = None
            return False

    def publish(self, topic: str, payload: bytes, retain: bool = False) -> bool:
        if self._client is None:
            if not self.connect():
                return False
        try:
            self._client.publish(topic, payload, retain=retain, qos=0)
            return True
        except Exception as e:
            print("[mqtt] publish failed, will reconnect:", e)
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
            return False

    def ping(self):
        if self._client is not None:
            try:
                self._client.ping()
            except Exception as e:
                print("[mqtt] ping failed:", e)
                self._client = None
