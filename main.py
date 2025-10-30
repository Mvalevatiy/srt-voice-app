import pysrt
import os
from pathlib import Path
import asyncio
import edge_tts
import subprocess
import tempfile
import shutil
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import threading
import glob
import json

# Конфігурація голосів Edge TTS
EDGE_VOICES = {
    "Ostap (чоловічий)": "uk-UA-OstapNeural",
    "Polina (жіночий)": "uk-UA-PolinaNeural"
}

# Пошук Piper моделей
def find_piper_models():
    """Знаходить завантажені моделі Piper з інформацією про спікерів"""
    models = {}
    voices_dir = "piper_voices"
    
    if os.path.exists(voices_dir):
        onnx_files = glob.glob(os.path.join(voices_dir, "**", "*.onnx"), recursive=True)
        for onnx_file in onnx_files:
            json_file = onnx_file + ".json"
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    num_speakers = config.get('num_speakers', 1)
                    
                    # Якщо кілька спікерів, створюємо окремі записи для кожного
                    if num_speakers > 1:
                        speaker_names = ["Катря", "Мирон", "Горпина"]
                        for speaker_id in range(num_speakers):
                            speaker_name = speaker_names[speaker_id] if speaker_id < len(speaker_names) else f"Голос {speaker_id + 1}"
                            friendly_name = f"{speaker_name} (український)"
                            models[friendly_name] = {
                                "model": onnx_file,
                                "config": json_file,
                                "speaker": speaker_id
                            }
                    else:
                        friendly_name = "Ukrainian TTS"
                        models[friendly_name] = {
                            "model": onnx_file,
                            "config": json_file,
                            "speaker": None
                        }
    
    return models

PIPER_MODELS = find_piper_models()

def parse_srt_file(srt_path):
    """Читає SRT файл та повертає список субтитрів"""
    try:
        subs = pysrt.open(srt_path, encoding='utf-8')
        return subs
    except Exception as e:
        return None

def get_timing_info(subtitle):
    """Витягує інформацію про тайминг з субтитру"""
    start_ms = subtitle.start.hours * 3600000 + \
               subtitle.start.minutes * 60000 + \
               subtitle.start.seconds * 1000 + \
               subtitle.start.milliseconds
    
    end_ms = subtitle.end.hours * 3600000 + \
             subtitle.end.minutes * 60000 + \
             subtitle.end.seconds * 1000 + \
             subtitle.end.milliseconds
    
    duration_ms = end_ms - start_ms
    
    return start_ms, end_ms, duration_ms

def get_last_subtitle_end_time(subs):
    """Отримує час закінчення останнього субтитру"""
    if not subs:
        return 0
    last_sub = subs[-1]
    _, end_ms, _ = get_timing_info(last_sub)
    return end_ms

async def edge_tts_synthesize(text, output_file, voice):
    """Озвучує текст через Edge TTS"""
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        return True
    except Exception as e:
        raise Exception(f"Edge TTS помилка: {e}")

def piper_tts_synthesize(text, output_file, model_path, config_path, speaker_id=None):
    """Озвучує текст через Piper TTS"""
    try:
        # Шукаємо piper.exe
        piper_exe = None
        possible_paths = [
            "piper\\piper.exe",
            "C:\\piper\\piper.exe",
            os.path.expanduser("~\\piper\\piper.exe")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                piper_exe = path
                break
        
        if not piper_exe:
            raise Exception("Piper.exe не знайдено! Встановіть Piper у папку 'piper' або 'C:\\piper'")
        
        # Piper створює WAV, тому спочатку створюємо тимчасовий WAV
        temp_wav = output_file.replace('.mp3', '_temp.wav')
        
        cmd = [
            piper_exe,
            '--model', model_path,
            '--config', config_path,
            '--output_file', temp_wav
        ]
        
        # Додаємо параметр speaker, якщо вказано
        if speaker_id is not None:
            cmd.extend(['--speaker', str(speaker_id)])
        
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = process.communicate(input=text.encode('utf-8'))
        
        if process.returncode != 0:
            raise Exception(f"Piper помилка: {stderr.decode()}")
        
        # Конвертуємо WAV в MP3 через FFmpeg
        if os.path.exists(temp_wav):
            convert_cmd = [
                'ffmpeg', '-i', temp_wav, '-codec:a', 'libmp3lame',
                '-qscale:a', '2', '-y', output_file
            ]
            subprocess.run(convert_cmd, capture_output=True, check=True)
            
            # Видаляємо тимчасовий WAV
            os.remove(temp_wav)
        else:
            raise Exception("Piper не створив аудіофайл")
        
        return True
    except Exception as e:
        raise Exception(f"Piper TTS помилка: {e}")

def text_to_speech(text, output_file, engine_type, voice_id):
    """Універсальна функція озвучки"""
    try:
        if engine_type == "edge":
            return asyncio.run(edge_tts_synthesize(text, output_file, voice_id))
        elif engine_type == "piper":
            model_info = PIPER_MODELS[voice_id]
            return piper_tts_synthesize(
                text, 
                output_file, 
                model_info["model"], 
                model_info["config"],
                model_info.get("speaker")
            )
    except Exception as e:
        raise e

def create_silence(duration_ms, output_file):
    """Створює тихий аудіофайл заданої тривалості"""
    if duration_ms <= 0:
        return
    duration_sec = duration_ms / 1000.0
    cmd = [
        'ffmpeg', '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo',
        '-t', str(duration_sec), '-q:a', '9', '-acodec', 'libmp3lame',
        '-y', output_file
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # Перевірка тривалості тиші
    probe_result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 
        'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
        output_file
    ], capture_output=True, text=True)
    actual = float(probe_result.stdout.strip()) * 1000
    print(f"DEBUG SILENCE: Потрібно {duration_ms:.0f}мс тиші, створено {actual:.0f}мс")

def adjust_audio_to_duration(input_file, output_file, target_duration_ms):
    """Підганяє швидкість одного аудіофрагменту під потрібну тривалість"""
    try:
        # Отримуємо поточну тривалість
        probe_cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
            input_file
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        current_duration_ms = float(result.stdout.strip()) * 1000

        print(f"DEBUG: Поточна: {current_duration_ms:.0f}мс, Потрібна: {target_duration_ms:.0f}мс, Різниця: {current_duration_ms - target_duration_ms:.0f}мс")
        
        # Якщо різниця менше 50мс, не чіпаємо
        if abs(current_duration_ms - target_duration_ms) < 50:
            if input_file != output_file:
                shutil.copy(input_file, output_file)
            return True
        
        target_duration_sec = target_duration_ms / 1000.0
        current_duration_sec = current_duration_ms / 1000.0
        speed_ratio = current_duration_sec / target_duration_sec
        
        # Обмежуємо швидкість
        if speed_ratio < 0.5 or speed_ratio > 2.0:
            print(f"DEBUG: Співвідношення {speed_ratio:.2f} поза межами, копіюю без змін")
            # Якщо не можемо підігнати, просто копіюємо
            if input_file != output_file:
                shutil.copy(input_file, output_file)
            return False
        
        # Застосовуємо atempo
        cmd = [
            'ffmpeg', '-i', input_file,
            '-filter:a', f'atempo={speed_ratio:.6f}',
            '-codec:a', 'libmp3lame', '-q:a', '2',
            '-y', output_file
        ]
        result = subprocess.run(cmd, capture_output=True, check=True)
        print(f"DEBUG: Застосовано atempo={speed_ratio:.3f}")

        # Перевірка результату
        if os.path.exists(output_file):
            probe_result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                output_file
            ], capture_output=True, text=True)
            final_duration = float(probe_result.stdout.strip()) * 1000
            print(f"DEBUG: Після корекції файл має {final_duration:.0f}мс (потрібно {target_duration_ms:.0f}мс)")
        else:
            print(f"DEBUG: ФАЙЛ НЕ СТВОРИВСЯ!")

        return True
        
    except Exception as e:
        if input_file != output_file:
            shutil.copy(input_file, output_file)
        return False    

def concatenate_audio_files(file_list, output_file):
    """Об'єднує аудіофайли в один"""
    list_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8')
    for file in file_list:
        escaped_path = file.replace('\\', '/').replace("'", "'\\''")
        list_file.write(f"file '{escaped_path}'\n")
    list_file.close()
    
    cmd = [
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', list_file.name, '-c', 'copy', '-y', output_file
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        os.unlink(list_file.name)
        return True
    except subprocess.CalledProcessError:
        os.unlink(list_file.name)
        return False

def play_audio(file_path):
    """Програє аудіофайл"""
    if os.name == 'nt':
        os.startfile(file_path)

def process_srt_to_audio(srt_path, engine_type, voice_id, voice_name, target_duration_ms, progress_callback, log_callback, stop_flag):
    """Головна функція: озвучує SRT файл з таймінгом"""
    log_callback(f"Обробка файлу: {os.path.basename(srt_path)}\n")
    log_callback(f"Движок: {'Edge TTS' if engine_type == 'edge' else 'Piper TTS'}\n")
    log_callback(f"Голос: {voice_name}\n\n")
    
    subs = parse_srt_file(srt_path)
    if not subs:
        log_callback("✗ Помилка читання файлу\n")
        return False
    
    log_callback(f"✓ Завантажено {len(subs)} субтитрів\n\n")
    
    temp_dir = tempfile.mkdtemp()
    audio_files = []
    current_time = 0
    
    try:
        # Тиша на початку, якщо перший субтитр не з 0
        if subs and len(subs) > 0:
            first_start_ms, _, _ = get_timing_info(subs[0])
            if first_start_ms > 0:
                initial_silence_file = os.path.join(temp_dir, "silence_initial.mp3")
                log_callback(f"Додавання тиші на початку: {first_start_ms}мс\n")
                create_silence(first_start_ms, initial_silence_file)
                audio_files.append(initial_silence_file)
                current_time = first_start_ms
                
        for i, sub in enumerate(subs, 1):
            # Перевірка на зупинку
            if stop_flag['stopped']:
                log_callback("\n⚠ Обробку зупинено користувачем\n")
                return False
            
            progress = int((i / len(subs)) * 100)
            progress_callback(progress)
            log_callback(f"[{i}/{len(subs)}] Обробка субтитру...\n")
            
            start_ms, end_ms, duration_ms = get_timing_info(sub)
            
            # Додаємо тишу ПЕРЕД субтитром, якщо є пауза
            if start_ms > current_time:
                silence_duration = start_ms - current_time
                silence_file = os.path.join(temp_dir, f"silence_{i:04d}.mp3")
                log_callback(f"  + Тиша: {silence_duration}мс\n")
                create_silence(silence_duration, silence_file)
                audio_files.append(silence_file)
            
            # Озвучуємо текст субтитру
            text = sub.text.replace('\n', ' ')
            audio_file_temp = os.path.join(temp_dir, f"audio_{i:04d}_temp.mp3")
            audio_file = os.path.join(temp_dir, f"audio_{i:04d}.mp3")
            
            try:
                if text_to_speech(text, audio_file_temp, engine_type, voice_id):
                    # Підганяємо тривалість озвучки під тайминг субтитру
                    adjust_audio_to_duration(audio_file_temp, audio_file, duration_ms)
                    audio_files.append(audio_file)  # <-- Тут має бути audio_file, НЕ audio_file_temp
                    
                    # Перевірка чи створився скоригований файл
                    if not os.path.exists(audio_file):
                        print(f"ПОМИЛКА: Скоригований файл не створився, використовую оригінал")
                        shutil.copy(audio_file_temp, audio_file)
                    
                    # Видаляємо тимчасовий файл
                    if os.path.exists(audio_file_temp):
                        os.remove(audio_file_temp)
                    
                    current_time = end_ms
            except Exception as e:
                log_callback(f"✗ Помилка озвучки субтитру {i}: {e}\n")
                return False        
        
        # Додаємо тишу В КІНЦІ, якщо вказана цільова тривалість
        if target_duration_ms and target_duration_ms > current_time:
            final_silence_duration = target_duration_ms - current_time
            final_silence_file = os.path.join(temp_dir, "silence_final.mp3")
            
            # Детальне логування
            log_callback(f"\n--- Розрахунок фінальної тиші ---\n")
            log_callback(f"Останній субтитр закінчився в: {current_time}мс ({current_time/1000:.1f}с)\n")
            log_callback(f"Цільова тривалість відео: {target_duration_ms}мс ({target_duration_ms/1000:.1f}с)\n")
            log_callback(f"Потрібно додати тиші: {final_silence_duration}мс ({final_silence_duration/1000:.1f}с)\n")
            
            create_silence(final_silence_duration, final_silence_file)
            audio_files.append(final_silence_file)
        elif target_duration_ms:
            log_callback(f"\n⚠ Озвучка довша за відео!\n")
            log_callback(f"Останній субтитр: {current_time}мс ({current_time/1000:.1f}с)\n")
            log_callback(f"Цільова тривалість: {target_duration_ms}мс ({target_duration_ms/1000:.1f}с)\n")
        
        if stop_flag['stopped']:
            log_callback("\n⚠ Обробку зупинено користувачем\n")
            return False
        
        log_callback("\nОб'єднання аудіофрагментів...\n")
        
        # Створюємо назву файлу з ім'ям голосу
        base_name = Path(srt_path).stem
        parent_dir = Path(srt_path).parent
        short_voice_name = voice_name.split()[0]
        output_filename = f"{short_voice_name} - {base_name}.mp3"
        output_path = parent_dir / output_filename
        
        if concatenate_audio_files(audio_files, str(output_path)):
            # Якщо вказана цільова тривалість, робимо фінальну корекцію
            if target_duration_ms and target_duration_ms > 0:
                log_callback("\nФінальна корекція тривалості...\n")
                
                # Перевіряємо поточну тривалість
                probe_cmd = [
                    'ffprobe', '-v', 'error', '-show_entries', 
                    'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(output_path)
                ]
                result = subprocess.run(probe_cmd, capture_output=True, text=True)
                current_duration_sec = float(result.stdout.strip())
                current_duration_ms = current_duration_sec * 1000
                
                target_duration_sec = target_duration_ms / 1000.0
                
                # Якщо різниця більше 0.5 секунди, коригуємо
                diff_sec = abs(current_duration_sec - target_duration_sec)
                if diff_sec > 0.5:
                    log_callback(f"Поточна тривалість: {current_duration_sec:.1f}с, цільова: {target_duration_sec:.1f}с\n")
                    log_callback(f"Різниця: {diff_sec:.1f}с, застосовую корекцію...\n")
                    
                    # Створюємо тимчасову копію
                    temp_path = str(output_path).replace('.mp3', '_before_final_correction.mp3')
                    os.rename(str(output_path), temp_path)
                    
                    # Розраховуємо коефіцієнт
                    speed_ratio = current_duration_sec / target_duration_sec
                    
                    if 0.5 <= speed_ratio <= 2.0:
                        # ПРОХІД 1: Застосовуємо корекцію
                        cmd = [
                            'ffmpeg', '-i', temp_path,
                            '-filter:a', f'atempo={speed_ratio:.6f}',
                            '-codec:a', 'libmp3lame', '-q:a', '2',
                            '-y', str(output_path)
                        ]
                        subprocess.run(cmd, capture_output=True, check=True)
                        
                        # Перевіряємо результат першого проходу
                        result = subprocess.run(probe_cmd, capture_output=True, text=True)
                        after_first_pass = float(result.stdout.strip())
                        log_callback(f"Після першого проходу: {after_first_pass:.1f}с\n")
                        
                        # ПРОХІД 2: Якщо різниця ще є, коригуємо знову
                        second_diff = abs(after_first_pass - target_duration_sec)
                        if second_diff > 1.0 and 0.5 <= (after_first_pass / target_duration_sec) <= 2.0:
                            log_callback(f"Різниця {second_diff:.1f}с, другий прохід корекції...\n")
                            
                            temp_path2 = str(output_path).replace('.mp3', '_temp2.mp3')
                            os.rename(str(output_path), temp_path2)
                            
                            speed_ratio2 = after_first_pass / target_duration_sec
                            cmd2 = [
                                'ffmpeg', '-i', temp_path2,
                                '-filter:a', f'atempo={speed_ratio2:.6f}',
                                '-codec:a', 'libmp3lame', '-q:a', '2',
                                '-y', str(output_path)
                            ]
                            subprocess.run(cmd2, capture_output=True, check=True)
                            os.remove(temp_path2)
                            
                            result = subprocess.run(probe_cmd, capture_output=True, text=True)
                            after_second_pass = float(result.stdout.strip())
                            log_callback(f"Після другого проходу: {after_second_pass:.1f}с\n")
                        
                        # Показуємо фінальний результат
                        result = subprocess.run(probe_cmd, capture_output=True, text=True)
                        final_duration_sec = float(result.stdout.strip())
                        final_diff = abs(final_duration_sec - target_duration_sec)
                        
                        log_callback(f"✓ Фінальна тривалість: {final_duration_sec:.1f}с (різниця: {final_diff:.1f}с)\n")
                        os.remove(temp_path)
                    else:
                        log_callback(f"⚠ Коефіцієнт {speed_ratio:.2f}x поза межами, залишаю як є\n")
                        os.rename(temp_path, str(output_path))
                else:
                    log_callback(f"✓ Тривалість в межах норми (різниця {diff_sec:.1f}с)\n")
            
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            
            # Показуємо фінальну тривалість
            probe_cmd = [
                'ffprobe', '-v', 'error', '-show_entries', 
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                str(output_path)
            ]
            result = subprocess.run(probe_cmd, capture_output=True, text=True)
            actual_duration_sec = float(result.stdout.strip())
            actual_min = int(actual_duration_sec // 60)
            actual_sec = int(actual_duration_sec % 60)
            
            log_callback(f"\n✓ Готово!\n")
            log_callback(f"Файл: {output_path}\n")
            log_callback(f"Розмір: {file_size:.2f} МБ\n")
            log_callback(f"Тривалість: {actual_min}:{actual_sec:02d}\n")
            return True
        else:
            log_callback("\n✗ Помилка об'єднання\n")
            return False
            
    except Exception as e:
        log_callback(f"\n✗ Критична помилка: {e}\n")
        return False
    finally:
        shutil.rmtree(temp_dir)

class SRTVoiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SRT Voice App - Українська озвучка")
        self.root.geometry("650x700")
        self.root.resizable(False, False)
        
        self.srt_file = None
        self.preview_file = None
        self.stop_flag = {'stopped': False}
        self.processing = False
        
        # Заголовок
        title_label = tk.Label(root, text="SRT Voice App", font=("Arial", 18, "bold"))
        title_label.pack(pady=15)
        
        subtitle_label = tk.Label(root, text="Озвучка субтитрів українською мовою", font=("Arial", 10))
        subtitle_label.pack(pady=(0, 15))
        
        # Вибір файлу
        file_frame = tk.Frame(root)
        file_frame.pack(pady=10, padx=20, fill=tk.X)
        
        self.file_label = tk.Label(file_frame, text="Файл не обрано", bg="#f0f0f0", anchor="w", padx=10, pady=5)
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        file_button = tk.Button(file_frame, text="Обрати SRT", command=self.select_file, width=15)
        file_button.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Вибір TTS движка
        engine_frame = tk.Frame(root)
        engine_frame.pack(pady=10, padx=20, fill=tk.X)
        
        engine_label = tk.Label(engine_frame, text="Движок TTS:")
        engine_label.pack(side=tk.LEFT)
        
        self.engine_var = tk.StringVar(value="edge")
        
        edge_rb = tk.Radiobutton(engine_frame, text="Edge TTS (онлайн)", 
                                 variable=self.engine_var, value="edge",
                                 command=self.update_voice_list)
        edge_rb.pack(side=tk.LEFT, padx=10)
        
        if PIPER_MODELS:
            piper_rb = tk.Radiobutton(engine_frame, text="Piper TTS (офлайн)", 
                                     variable=self.engine_var, value="piper",
                                     command=self.update_voice_list)
            piper_rb.pack(side=tk.LEFT, padx=10)
        else:
            piper_label = tk.Label(engine_frame, text="(Piper моделі не знайдено)", fg="gray")
            piper_label.pack(side=tk.LEFT, padx=10)
        
        # Поле для цільової тривалості
        duration_frame = tk.Frame(root)
        duration_frame.pack(pady=10, padx=20, fill=tk.X)
        
        duration_label = tk.Label(duration_frame, text="Тривалість відео (хв:сек):")
        duration_label.pack(side=tk.LEFT)
        
        self.duration_min_var = tk.StringVar(value="")
        self.duration_sec_var = tk.StringVar(value="")
        
        tk.Label(duration_frame, text="  ").pack(side=tk.LEFT)
        duration_min_entry = tk.Entry(duration_frame, textvariable=self.duration_min_var, width=5)
        duration_min_entry.pack(side=tk.LEFT)
        tk.Label(duration_frame, text=" хв ").pack(side=tk.LEFT)
        
        duration_sec_entry = tk.Entry(duration_frame, textvariable=self.duration_sec_var, width=5)
        duration_sec_entry.pack(side=tk.LEFT)
        tk.Label(duration_frame, text=" сек").pack(side=tk.LEFT)
        
        tk.Label(duration_frame, text="  (для додавання тиші в кінці)", fg="gray").pack(side=tk.LEFT)
        
        # Вибір голосу
        voice_frame = tk.Frame(root)
        voice_frame.pack(pady=10, padx=20, fill=tk.X)
        
        voice_label = tk.Label(voice_frame, text="Голос:")
        voice_label.pack(side=tk.LEFT)
        
        self.voice_var = tk.StringVar()
        self.voice_menu = ttk.Combobox(voice_frame, textvariable=self.voice_var, 
                                       state="readonly", width=30)
        self.voice_menu.pack(side=tk.LEFT, padx=10)
        
        preview_button = tk.Button(voice_frame, text="🔊 Прослухати", 
                                   command=self.preview_voice, width=12)
        preview_button.pack(side=tk.LEFT, padx=5)
        
        # Оновлюємо список голосів
        self.update_voice_list()
        
        # Кнопки запуску та зупинки
        buttons_frame = tk.Frame(root)
        buttons_frame.pack(pady=15, padx=20, fill=tk.X)
        
        self.start_button = tk.Button(buttons_frame, text="▶ Запустити озвучку", 
                                      command=self.start_processing, 
                                      font=("Arial", 12, "bold"), bg="#4CAF50", 
                                      fg="white", height=2, cursor="hand2")
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.stop_button = tk.Button(buttons_frame, text="⬛ Зупинити", 
                                     command=self.stop_processing,
                                     font=("Arial", 12, "bold"), bg="#f44336", 
                                     fg="white", height=2, cursor="hand2",
                                     state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Прогрес бар
        self.progress = ttk.Progressbar(root, mode='determinate', length=610)
        self.progress.pack(pady=10, padx=20)
        
        # Лог
        log_frame = tk.Frame(root)
        log_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, height=12, state=tk.DISABLED, 
                               yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.log_text.yview)
    
    def update_voice_list(self):
        """Оновлює список голосів залежно від обраного движка"""
        engine = self.engine_var.get()
        
        if engine == "edge":
            voices = list(EDGE_VOICES.keys())
        else:
            voices = list(PIPER_MODELS.keys())
        
        self.voice_menu['values'] = voices
        if voices:
            self.voice_var.set(voices[0])
    
    def select_file(self):
        file_paths = filedialog.askopenfilenames(
            title="Оберіть SRT файли",
            filetypes=[("SRT файли", "*.srt"), ("Всі файли", "*.*")]
        )
        if file_paths:
            self.srt_file = list(file_paths)
            count = len(file_paths)
            if count == 1:
                display_text = os.path.basename(file_paths[0])
            else:
                display_text = f"Обрано {count} файлів"
            self.file_label.config(text=display_text)
            self.log(f"Обрано файлів: {count}\n")
            for f in file_paths:
                self.log(f"  - {os.path.basename(f)}\n")
    
    def ask_durations_for_files(self, files):
        """Запитує тривалість для кожного файлу"""
        durations = {}
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Тривалість для кожного файлу")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Вкажіть тривалість відео для кожного файлу:", 
                font=("Arial", 11, "bold")).pack(pady=10)
        
        tk.Label(dialog, text="(Залиште порожнім для автоматичної тривалості)", 
                fg="gray").pack(pady=(0, 10))
        
        # Створюємо фрейм зі скролом
        canvas = tk.Canvas(dialog)
        scrollbar = tk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        entries = {}
        
        for idx, file_path in enumerate(files, 1):
            file_frame = tk.Frame(scrollable_frame)
            file_frame.pack(pady=5, padx=10, fill=tk.X)
            
            # Назва файлу
            tk.Label(file_frame, text=f"{idx}. {os.path.basename(file_path)}", 
                    anchor="w", width=40).pack(side=tk.LEFT)
            
            # Поля введення
            min_var = tk.StringVar()
            sec_var = tk.StringVar()
            
            tk.Entry(file_frame, textvariable=min_var, width=5).pack(side=tk.LEFT, padx=2)
            tk.Label(file_frame, text="хв").pack(side=tk.LEFT)
            tk.Entry(file_frame, textvariable=sec_var, width=5).pack(side=tk.LEFT, padx=2)
            tk.Label(file_frame, text="сек").pack(side=tk.LEFT)
            
            entries[file_path] = (min_var, sec_var)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10, padx=(0, 10))
        
        # Кнопки
        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=10)
        
        result = {'confirmed': False}
        
        def on_confirm():
            for file_path, (min_var, sec_var) in entries.items():
                try:
                    minutes = int(min_var.get() or 0)
                    seconds = int(sec_var.get() or 0)
                    if minutes > 0 or seconds > 0:
                        durations[file_path] = (minutes * 60 + seconds) * 1000
                    else:
                        durations[file_path] = None
                except:
                    durations[file_path] = None
            result['confirmed'] = True
            dialog.destroy()
        
        def on_cancel():
            dialog.destroy()
        
        tk.Button(button_frame, text="Підтвердити", command=on_confirm, 
                bg="#4CAF50", fg="white", width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Скасувати", command=on_cancel, 
                width=15).pack(side=tk.LEFT, padx=5)
        
        dialog.wait_window()
        
        if result['confirmed']:
            return durations
        else:
            return None
    
    def preview_voice(self):
        """Передпрослуховування обраного голосу"""
        engine = self.engine_var.get()
        voice_name = self.voice_var.get()
        
        if not voice_name:
            messagebox.showwarning("Увага", "Оберіть голос!")
            return
        
        self.log(f"Створення прослуховування: {voice_name}...\n")
        
        if self.preview_file and os.path.exists(self.preview_file):
            try:
                os.remove(self.preview_file)
            except:
                pass
        
        self.preview_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3').name
        sample_text = "Привіт! Це приклад озвучки. Так звучатиме ваш текст."
        
        def preview_thread():
            try:
                if engine == "edge":
                    voice_id = EDGE_VOICES[voice_name]
                else:
                    voice_id = voice_name
                
                if text_to_speech(sample_text, self.preview_file, engine, voice_id):
                    self.log(f"✓ Програю зразок голосу...\n")
                    play_audio(self.preview_file)
                else:
                    self.root.after(0, lambda: messagebox.showerror("Помилка", 
                                    "Не вдалося створити прослуховування"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Помилка", 
                                f"Помилка прослуховування: {str(e)}"))
                self.root.after(0, lambda: self.log(f"✗ {str(e)}\n"))
        
        thread = threading.Thread(target=preview_thread)
        thread.start()
    
    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def update_progress(self, value):
        self.progress['value'] = value
    
    def start_processing(self):
        if not self.srt_file:
            messagebox.showwarning("Увага", "Будь ласка, оберіть SRT файл(и)!")
            return
        
        if not self.voice_var.get():
            messagebox.showwarning("Увага", "Будь ласка, оберіть голос!")
            return
        
        # Якщо кілька файлів, запитуємо тривалість для кожного
        files_to_process = self.srt_file if isinstance(self.srt_file, list) else [self.srt_file]
        
        if len(files_to_process) > 1:
            durations_dict = self.ask_durations_for_files(files_to_process)
            if durations_dict is None:  # Користувач натиснув "Скасувати"
                return
        else:
            # Для одного файлу використовуємо загальне поле
            try:
                minutes = int(self.duration_min_var.get() or 0)
                seconds = int(self.duration_sec_var.get() or 0)
                target_duration = (minutes * 60 + seconds) * 1000 if (minutes > 0 or seconds > 0) else None
            except:
                target_duration = None
            durations_dict = {files_to_process[0]: target_duration}
        
        self.processing = True
        self.stop_flag['stopped'] = False
        self.start_button.config(state=tk.DISABLED, text="⏳ Обробка...")
        self.stop_button.config(state=tk.NORMAL)
        self.progress['value'] = 0
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        engine = self.engine_var.get()
        voice_name = self.voice_var.get()
        
        if engine == "edge":
            voice_id = EDGE_VOICES[voice_name]
        else:
            voice_id = voice_name
        
        thread = threading.Thread(target=self.process_thread, args=(engine, voice_id, voice_name, durations_dict))
        thread.start()
    
    def stop_processing(self):
        """Зупиняє обробку"""
        self.stop_flag['stopped'] = True
        self.stop_button.config(state=tk.DISABLED, text="⏹ Зупинка...")
        self.log("\n⚠ Зупинка обробки...\n")
    
    def process_thread(self, engine, voice_id, voice_name, durations_dict):
        files_to_process = self.srt_file if isinstance(self.srt_file, list) else [self.srt_file]
        
        total_files = len(files_to_process)
        successful = 0
        
        for idx, srt_file in enumerate(files_to_process, 1):
            if self.stop_flag['stopped']:
                break
            
            self.root.after(0, lambda i=idx, t=total_files: 
                        self.log(f"\n{'='*60}\nФайл {i} з {t}\n{'='*60}\n"))
            
            try:
                # Отримуємо тривалість для цього файлу
                target_duration_ms = durations_dict.get(srt_file, None)
                
                success = process_srt_to_audio(
                    srt_file,
                    engine,
                    voice_id,
                    voice_name,
                    target_duration_ms,
                    self.update_progress,
                    self.log,
                    self.stop_flag
                )
                
                if success:
                    successful += 1
            except Exception as e:
                self.root.after(0, lambda e=e: self.log(f"\n✗ Критична помилка: {e}\n"))
    
        # Підсумок
        if successful == total_files:
            self.root.after(0, lambda: messagebox.showinfo("Готово", 
                           f"Успішно оброблено всі {total_files} файл(ів)!"))
            self.root.after(0, lambda: self.log(f"\n{'='*60}\n✓ ГОТОВО: {successful}/{total_files}\n{'='*60}\n"))
        elif successful > 0:
            self.root.after(0, lambda: messagebox.showwarning("Частково готово", 
                           f"Оброблено {successful} з {total_files} файлів"))
            self.root.after(0, lambda: self.log(f"\n{'='*60}\n⚠ Оброблено: {successful}/{total_files}\n{'='*60}\n"))
        elif not self.stop_flag['stopped']:
            self.root.after(0, lambda: messagebox.showerror("Помилка", 
                           "Не вдалося обробити жоден файл. Перевірте лог."))
        
        self.processing = False
        self.root.after(0, lambda: self.start_button.config(state=tk.NORMAL, text="▶ Запустити озвучку"))
        self.root.after(0, lambda: self.stop_button.config(state=tk.DISABLED, text="⬛ Зупинити"))
    
    def __del__(self):
        if self.preview_file and os.path.exists(self.preview_file):
            try:
                os.remove(self.preview_file)
            except:
                pass

if __name__ == "__main__":
    root = tk.Tk()
    app = SRTVoiceApp(root)
    root.mainloop()