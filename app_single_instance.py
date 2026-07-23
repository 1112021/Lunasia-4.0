# -*- coding: utf-8 -*-
"""第二实例激活第一实例窗口（QLocalServer / QLocalSocket）。"""
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

INSTANCE_KEY = "LuciniaAI_Lunasia_instance_v1"


def try_activate_existing_instance():
    """若已有实例在监听，则通知其置顶并返回 True。"""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(2000):
        sock.write(b"RAISE\n")
        sock.waitForBytesWritten(3000)
        sock.disconnectFromServer()
        sock.close()
        return True
    sock.abort()
    return False


class SingleInstanceGuard(QObject):
    """
    第一实例：监听本地套接字。
    在 set_target_window 之前收到的连接会记为 pending，绑定后立即处理一次。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window = None
        self._activate_pending = False
        self._server = QLocalServer(self)
        QLocalServer.removeServer(INSTANCE_KEY)
        if not self._server.listen(INSTANCE_KEY):
            print(f"⚠️ 单实例监听失败: {self._server.errorString()}")
        self._server.newConnection.connect(self._on_new_connection)

    def set_target_window(self, window):
        """主窗口创建完成后调用，避免长初始化期间丢失激活请求。"""
        self._window = window
        if self._activate_pending and window is not None:
            self._activate_pending = False
            QTimer.singleShot(0, window.raise_from_second_instance)

    def _on_new_connection(self):
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(2000)
            conn.readAll()
            conn.close()
        w = self._window
        if w is not None:
            QTimer.singleShot(0, w.raise_from_second_instance)
        else:
            self._activate_pending = True
