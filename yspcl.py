import sys
import subprocess
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
    QLineEdit, QLabel, QComboBox, QMessageBox, QProgressBar, QHBoxLayout
)

# ffmpeg 处理函数
def ffmpeg_process(input_file, output_format=None, resolution=None, task_type="转换格式+调整分辨率"):
    try:
        output_file = input_file.rsplit('.', 1)[0]  # 去掉原文件扩展名
        cmd = ["ffmpeg", "-i", input_file]

        # 根据任务类型组合命令
        if task_type == "转换格式":
            if not output_format:
                raise ValueError("未选择输出格式")
            output_file += f".{output_format}"
        elif task_type == "调整分辨率":
            if not resolution:
                raise ValueError("未输入分辨率")
            cmd += ["-vf", f"scale={resolution}"]
            output_file += "_resized." + input_file.rsplit('.', 1)[1]
        elif task_type == "转换格式+调整分辨率":
            if not output_format or not resolution:
                raise ValueError("请同时输入格式和分辨率")
            cmd += ["-vf", f"scale={resolution}"]
            output_file += f"_resized.{output_format}"

        cmd.append(output_file)

        subprocess.run(cmd, check=True)
        return output_file
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg 执行失败: {e}")
    except Exception as e:
        raise RuntimeError(str(e))


class MediaConverter(QWidget):
    def __init__(self):
        super().__init__()
        self.file_path = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 选择文件按钮
        self.file_label = QLabel("未选择文件")
        btn_select = QPushButton("选择文件")
        btn_select.clicked.connect(self.select_file)
        layout.addWidget(self.file_label)
        layout.addWidget(btn_select)

        # 任务类型
        self.task_combo = QComboBox()
        self.task_combo.addItems(["转换格式", "调整分辨率", "转换格式+调整分辨率"])
        layout.addWidget(QLabel("任务类型:"))
        layout.addWidget(self.task_combo)

        # 格式选择
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mp4", "avi", "mov", "mkv", "webm", "mp3", "wav"])
        layout.addWidget(QLabel("输出格式:"))
        layout.addWidget(self.format_combo)

        # 分辨率输入
        self.res_input = QLineEdit()
        self.res_input.setPlaceholderText("如 1280:720")
        layout.addWidget(QLabel("分辨率:"))
        layout.addWidget(self.res_input)

        # 操作按钮
        btn_start = QPushButton("开始转换")
        btn_start.clicked.connect(self.start_operation)
        layout.addWidget(btn_start)

        # 进度条
        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.setLayout(layout)
        self.setWindowTitle("音视频处理工具")

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "所有文件 (*.*)")
        if file_path:
            self.file_path = file_path
            self.file_label.setText(f"已选择: {file_path}")

    def start_operation(self):
        if not self.file_path:
            QMessageBox.warning(self, "提示", "请先选择文件")
            return

        task_type = self.task_combo.currentText()
        output_format = self.format_combo.currentText() if "格式" in task_type else None
        resolution = self.res_input.text() if "分辨率" in task_type else None

        try:
            output_file = ffmpeg_process(
                self.file_path,
                output_format=output_format,
                resolution=resolution,
                task_type=task_type
            )
            self.progress.setValue(100)
            QMessageBox.information(self, "完成", f"操作成功，输出文件：{output_file}")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MediaConverter()
    win.show()
    sys.exit(app.exec())
