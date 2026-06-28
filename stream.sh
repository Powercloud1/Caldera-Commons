#!/bin/bash
WIDTH=854
HEIGHT=480
FPS=20
VID_BITRATE=600k
AUDIO_BITRATE=64k

ffmpeg -re \
  -f v4l2 -framerate "$FPS" -video_size "${WIDTH}x${HEIGHT}" -i /dev/video0 \
  -f alsa -i plughw:USB,0 \
  -af "pan=mono|c0=FL,volume=2.5" \
  -c:v libx264 -preset veryfast -tune zerolatency -profile:v baseline -level 3.1 \
  -pix_fmt yuv420p -g 30 -b:v "$VID_BITRATE" -maxrate 800k -bufsize 1200k \
  -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 \
  -f flv rtmp://127.0.0.1:1935/live/stream