"""Configuration settings for the AI Object Detection Application."""

import os

# Model & IO Paths
MODEL_PATH = "/home/nohope/Code/01.Code/StarLink/AI_Pipeline/Tools/Model/best.pt"
DEFAULT_RTSP = "rtsp://admin:Abcd@1234@10.2.50.117:554/Streaming/Channels/101"
OUTPUT_DIR = "output"

# UI Configuration
WINDOW_TITLE = "AI Object Detection Inspector"
WINDOW_GEOMETRY = "1200x720"
THEME_MODE = "Dark"
THEME_COLOR = "blue"

# AI Inference Settings
CONFIDENCE_THRESHOLD = 0.1
MAX_QUEUE_SIZE = 2

# Colors (OpenCV format: BGR)
COLOR_OK = (0, 255, 0)
COLOR_NG = (0, 0, 255)
COLOR_IDLE = (0, 255, 255)
COLOR_WHITE = (255, 255, 255)
