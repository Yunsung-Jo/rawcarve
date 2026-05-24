from dataclasses import dataclass


@dataclass
class FileHit:
    file_type: str  # "jpeg" | "avi"
    offset: int
