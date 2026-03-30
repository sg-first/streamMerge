from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit
from GUI.Resources import resource
from GUI.Color import QSLauncherColor
from PySide6.QtCore import QObject, Signal
import logging
import os
from logging.handlers import TimedRotatingFileHandler

class LogSignal(QObject):
    log_message = Signal(str, str)

class QSLogWidget(QTextEdit):
    def __init__(self, parent=None):
        super(QSLogWidget, self).__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet('QTextEdit{border-image: url(":/P4Merge/icons/terminal.png");\nfont: 10pt "Consolas";\n}')
        self.log_signal = LogSignal()
        self.log_signal.log_message.connect(self.log)

        # 创建日志文件夹
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # 配置日志记录器
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

        handler = TimedRotatingFileHandler(
            os.path.join(log_dir, "p4merge.log"),
            when="midnight",
            interval=1,
            backupCount=7,  # 可以设置保留的日志文件数量
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.logger.addHandler(handler)

    def log(self, content: str, color=QSLauncherColor.White, log_level=logging.INFO):
        self.append('<font color="%s">%s</font>' % (color, content.replace(' ', '&nbsp;').replace('\n', '<br>')))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

        # 同时将日志记录到文件
        self.log_to_file(content, log_level)

    def log_to_file(self, content: str, log_level=logging.INFO):
        # 将日志记录到文件
        if log_level == logging.WARNING:
            self.logger.warning(content)
        elif log_level == logging.ERROR:
            self.logger.error(content)
        else:
            self.logger.info(content)

    def warning(self, content: str):
        self.log(content, self.Color_Warning, logging.WARNING)

    def error(self, content: str):
        self.log(content, self.Color_Error, logging.ERROR)