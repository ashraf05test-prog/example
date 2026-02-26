from flask import Flask, render_template, request, jsonify, Response
from threading import Thread
import subprocess
import asyncio
import os
import uuid
import json
import requests
import shutil
import re
from bs4 import BeautifulSoup

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

tasks = {}

def update_task(task_id, status, message, progress=0, link=None, error=None):
    tasks[task_id] = {
        'status': status,
        'message': message,
        'progress': progress,
        'link': link,
        'error': error
    }

def extract_links(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://google.com',
        }
        response = requests.get(url, headers=headers, timeout=20)
        text = response.text
        m3u8_url = None
        subtitle_url = None

        m3u8_patterns = [
            r'https?://[^\s"\'\\]+\.m3u8[^\s"\'\\]*',
            r'file["\s]*:["\s]*["\']?(https?://[^"\'\\]+\.m3u8[^"\'\\]*)',
            r'source["\s]*:["\s]*["\']?(https?://[^"\'\\]+\.m3u8[^"\'\\]*)',
        ]
        for pattern in m3u8_patterns:
            matches = re.findall(pattern, text)
            if matches:
                m3u8_url = matches[0] if isinstance(matches[0], str) else matches[0][-1]
                break

        if not m3u8_url:
            soup = BeautifulSoup(text, 'html.parser')
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if src and ('embed' in src or 'player' in src or 'watch' in src):
                    try:
                        if not src.startswith('http'):
                            src = 'https:' + src if src.startswith('//') else url.rstrip('/') + '/' + src.lstrip('/')
                        iframe_resp = requests.get(src, headers=headers, timeout=15)
                        for pattern in m3u8_patterns:
                            matches = re.findall(pattern, iframe_resp.text)
                            if matches:
                                m3u8_url = matches[0] if isinstance(matches[0], str) else matches[0][-1]
                                break
                    except:
                        pass
                if m3u8_url:
                    break

        sub_patterns = [
            r'https?://[^\s"\'\\]+\.(vtt|srt)[^\s"\'\\]*',
            r'subtitle["\s]*:["\s]*["\']?(https?://[^"\'\\]+\.(vtt|srt)[^"\'\\]*)',
        ]
        for pattern in sub_patterns:
            matches = re.findall(pattern, text)
            if matches:
                m = matches[0]
                if isinstance(m, str) and m.startswith('http'):
                    subtitle_url = m
                elif isinstance(m, tuple):
                    for part in m:
                        if part.startswith('http'):
                            subtitle_url = part
                            break
                if subtitle_url:
                    break

        soup2 = BeautifulSoup(text, 'html.parser')
        for track in soup2.find_all('track'):
            src = track.get('src', '')
            if src and ('.vtt' in src or '.srt' in src):
                subtitle_url = src if src.startswith('http') else 'https:' + src if src.startswith('//') else url.rstrip('/') + '/' + src.lstrip('/')
                break

        return {'m3u8': m3u8_url, 'subtitle': subtitle_url}
    except Exception as e:
        return {'error': str(e), 'm3u8': None, 'subtitle': None}

def download_video(m3u8_url, output_path, task_id):
    update_task(task_id, 'downloading', '⏳ ভিডিও ডাউনলোড হচ্ছে...', 10)
    cmd = [
        'ffmpeg', '-y',
        '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        '-headers', 'Referer: https://seehd24.rpmvip.com/\r\nOrigin: https://seehd24.rpmvip.com',
        '-i', m3u8_url,
        '-c', 'copy',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f'ডাউনলোড ব্যর্থ: {result.stderr[-500:]}')

def burn_subtitle(input_path, subtitle_path, output_path, settings, task_id):
    update_task(task_id, 'processing', '🎬 সাবটাইটেল যোগ হচ্ছে...', 60)
    font = settings.get('font', 'Noto Sans Bengali')
    size = settings.get('size', 24)
    color = settings.get('color', 'white')
    position = settings.get('position', 'bottom')
    background = settings.get('background', 'none')
    bold = settings.get('bold', 0)
    italic = settings.get('italic', 0)
    color_map = {'white': '&H00FFFFFF', 'yellow': '&H0000FFFF', 'cyan': '&H00FFFF00'}
    ass_color = color_map.get(color, '&H00FFFFFF')
    align = 2
    if position == 'top': align = 8
    elif position == 'middle': align = 5
    back_style = ''
    if background == 'semi': back_style = ',BackColour=&H80000000,BorderStyle=4'
    elif background == 'black': back_style = ',BackColour=&HFF000000,BorderStyle=4'
    style = f"FontName={font},FontSize={size},PrimaryColour={ass_color},Bold={bold},Italic={italic},Alignment={align}{back_style}"
    safe_subtitle = subtitle_path.replace('\\', '/').replace(':', '\\:')
    cmd = [
        'ffmpeg', '-y',
        '-i', input_path,
        '-vf', f"subtitles='{safe_subtitle}':force_style='{style}'",
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '28',
        '-c:a', 'copy',
        '-threads', '0',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f'প্রসেসিং ব্যর্থ: {result.stderr[-500:]}')

def translate_subtitle(subtitle_path, engine, task_id):
    update_task(task_id, 'translating', '🌐 অনুবাদ হচ্ছে...', 40)
    with open(subtitle_path, 'r', encoding='utf-8') as f:
        content = f.read()
    if engine == 'gemini':
        import google.generativeai as genai
        genai.configure(api_key='AIzaSyAD9UcxHD474DyKE5iYmrNKLh5xInOodLk')
        model = genai.GenerativeModel('gemini-pro')
        lines = content.split('\n')
        translated_lines = []
        batch = []
        batch_indices = []
        for i, line in enumerate(lines):
            if line.strip() and not line.strip().isdigit() and '-->' not in line:
                batch.append(line)
                batch_indices.append(i)
                if len(batch) >= 20:
                    text = '\n'.join(batch)
                    response = model.generate_content(f"Translate to Bengali only, return same number of lines:\n{text}")
                    translated = response.text.strip().split('\n')
                    for j, idx in enumerate(batch_indices):
                        translated_lines.append(translated[j] if j < len(translated) else batch[j])
                    batch = []
                    batch_indices = []
            else:
                if batch:
                    text = '\n'.join(batch)
                    response = model.generate_content(f"Translate to Bengali only, return same number of lines:\n{text}")
                    translated = response.text.strip().split('\n')
                    for j, idx in enumerate(batch_indices):
                        translated_lines.append(translated[j] if j < len(translated) else batch[j])
                    batch = []
                    batch_indices = []
                translated_lines.append(line)
        translated_content = '\n'.join(translated_lines)
    else:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='en', target='bn')
        lines = content.split('\n')
        translated_lines = []
        for line in lines:
            if line.strip() and not line.strip().isdigit() and '-->' not in line:
                try:
                    translated_lines.append(translator.translate(line))
                except:
                    translated_lines.append(line)
            else:
                translated_lines.append(line)
        translated_content = '\n'.join(translated_lines)
    translated_path = subtitle_path.rsplit('.', 1)[0] + '_bn.srt'
    with open(translated_path, 'w', encoding='utf-8') as f:
        f.write(translated_content)
    return translated_path

async def upload_telegram(file_path, title, caption, task_id):
    from pyrogram import Client
    update_task(task_id, 'uploading', '📤 টেলিগ্রামে আপলোড হচ্ছে...', 80)
    async with Client(
        "anisub_bot",
        api_id=35315188,
        api_hash="ccf9a114d0b6401bddec3f0aa243a029",
        bot_token="8762932401:AAHoWrdYm8fhIt2e1RB-qktQhc5gFFa1ONQ",
        in_memory=True
    ) as client:
        msg = await client.send_video(
            chat_id=-1003248434147,
            video=file_path,
            caption=f"**{title}**\n{caption}" if caption else f"**{title}**",
            supports_streaming=True
        )
        return f"https://t.me/AniSubBD/{msg.id}"

def process_task(task_id, data, subtitle_file_data=None, subtitle_filename=None):
    try:
        work_dir = f"/tmp/{task_id}"
        os.makedirs(work_dir, exist_ok=True)
        m3u8_url = data.get('m3u8_url')
        subtitle_url = data.get('subtitle_url')
        subtitle_tab = data.get('subtitle_tab', 'url')
        translate_engine = data.get('translate_engine', 'google')
        settings = data.get('settings', {})
        title = data.get('title', 'AniSub Video')
        caption = data.get('caption', '')
        video_path = f"{work_dir}/video.mp4"
        subtitle_path = f"{work_dir}/subtitle.srt"
        output_path = f"{work_dir}/output.mp4"
        download_video(m3u8_url, video_path, task_id)
        if subtitle_tab == 'upload' and subtitle_file_data:
            with open(subtitle_path, 'wb') as f:
                f.write(subtitle_file_data)
        elif subtitle_tab == 'url' and subtitle_url:
            update_task(task_id, 'downloading', '⏳ সাবটাইটেল ডাউনলোড হচ্ছে...', 30)
            r = requests.get(subtitle_url, headers={'User-Agent': 'Mozilla/5.0'})
            with open(subtitle_path, 'wb') as f:
                f.write(r.content)
        elif subtitle_tab == 'translate':
            if subtitle_file_data:
                with open(subtitle_path, 'wb') as f:
                    f.write(subtitle_file_data)
            elif subtitle_url:
                r = requests.get(subtitle_url, headers={'User-Agent': 'Mozilla/5.0'})
                with open(subtitle_path, 'wb') as f:
                    f.write(r.content)
            subtitle_path = translate_subtitle(subtitle_path, translate_engine, task_id)
        burn_subtitle(video_path, subtitle_path, output_path, settings, task_id)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        link = loop.run_until_complete(upload_telegram(output_path, title, caption, task_id))
        loop.close()
        update_task(task_id, 'done', '✅ সম্পন্ন!', 100, link=link)
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception as e:
        update_task(task_id, 'error', f'❌ ব্যর্থ: {str(e)}', error=str(e))

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract():
    url = request.json.get('url')
    result = extract_links(url)
    return jsonify(result)

@app.route('/upload', methods=['POST'])
def upload():
    task_id = str(uuid.uuid4())[:8]
    subtitle_file = request.files.get('subtitle_file')
    subtitle_file_data = subtitle_file.read() if subtitle_file else None
    subtitle_filename = subtitle_file.filename if subtitle_file else None
    data = {
        'm3u8_url': request.form.get('m3u8_url'),
        'subtitle_url': request.form.get('subtitle_url'),
        'subtitle_tab': request.form.get('subtitle_tab', 'url'),
        'translate_engine': request.form.get('translate_engine', 'google'),
        'title': request.form.get('title', 'AniSub Video'),
        'caption': request.form.get('caption', ''),
        'settings': {
            'font': request.form.get('font', 'Noto Sans Bengali'),
            'size': int(request.form.get('size', 24)),
            'color': request.form.get('color', 'white'),
            'position': request.form.get('position', 'bottom'),
            'background': request.form.get('background', 'none'),
            'bold': int(request.form.get('bold', 0)),
            'italic': int(request.form.get('italic', 0)),
        }
    }
    update_task(task_id, 'starting', '⏳ শুরু হচ্ছে...', 0)
    thread = Thread(target=process_task, args=(task_id, data, subtitle_file_data, subtitle_filename))
    thread.daemon = True
    thread.start()
    return jsonify({'task_id': task_id})

@app.route('/status/<task_id>', methods=['GET'])
def status(task_id):
    task = tasks.get(task_id, {'status': 'not_found', 'message': 'Task পাওয়া যায়নি'})
    return jsonify(task)

@app.route('/progress/<task_id>')
def progress(task_id):
    def generate():
        import threading
        while True:
            task = tasks.get(task_id, {})
            yield f"data: {json.dumps(task)}\n\n"
            if task.get('status') in ['done', 'error']:
                break
            e = threading.Event()
            e.wait(timeout=2)
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
