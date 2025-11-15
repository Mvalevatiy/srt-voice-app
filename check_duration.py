import subprocess
import sys

if len(sys.argv) < 2:
    print("Використання: python check_duration.py шлях_до_файлу.mp3")
    sys.exit(1)

file_path = sys.argv[1]

# Перевірка через FFprobe
cmd = [
    'ffprobe', '-v', 'error', '-show_entries', 
    'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
    file_path
]

result = subprocess.run(cmd, capture_output=True, text=True)
duration_sec = float(result.stdout.strip())

minutes = int(duration_sec // 60)
seconds = int(duration_sec % 60)

print(f"Тривалість файлу: {duration_sec:.2f} секунд")
print(f"Це: {minutes}:{seconds:02d}")