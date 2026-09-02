"""文件域：产物登记 / 上传 / 预览 / 头像（FileService，底层存储走 infrastructure）。"""

from app.domain.file.service import FileService, file_preview_path

__all__ = ["FileService", "file_preview_path"]
